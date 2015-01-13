import pysam, sys, os, collections, datetime, operator
from jobTree.src.bioio import fastaRead, system, fastaWrite, logger
import numpy as np
from margin.utils import *
import math
from cactus.bar.cactus_expectationMaximisation import Hmm
from itertools import product
try:
    import cPickle 
except ImportError:
    import pickle as cPickle
    
BASES = "ACGT"

def marginCallerTargetFn(target, samFile, referenceFastaFile, outputVcfFile,  options):
    """Calculates the posterior probabilities of all the matches in between
    each pairwise alignment of a read to the reference. The collates this 
    posterior probabilities and uses them to call SNVs.
    """
    target.setFollowOnTargetFn(paralleliseSamProcessingTargetFn, 
                               args=(samFile, referenceFastaFile, outputVcfFile, 
                                     posteriorProbabilityCalculationTargetFn, 
                                     variantCallSamFileTargetFn, options))
   
def posteriorProbabilityCalculationTargetFn(target, exonerateCigarStringFile, 
                referenceSequenceName, referenceSequence, querySequenceFile, 
                outputPosteriorProbsFile, options):
    """Calculates the posterior probabilities of matches in a set of pairwise
    alignments between a reference sequence and a set of reads. 
    """
    #Temporary files
    tempRefFile = os.path.join(target.getLocalTempDir(), "ref.fa")
    tempReadFile = os.path.join(target.getLocalTempDir(), "read.fa")
    
    #Write the temporary reference file.
    fastaWrite(tempRefFile, referenceSequenceName, referenceSequence) 
    
    #Hash to store posterior probabilities in
    expectationsOfBasesAtEachPosition = {}
    
    #For each cigar string
    for exonerateCigarString, (querySequenceName, querySequence) in \
    zip(open(exonerateCigarStringFile, "r"), fastaRead(querySequenceFile)):
        fastaWrite(tempReadFile, querySequenceName, querySequence)
        #Call to cactus_realign
        tempPosteriorProbsFile = os.path.join(target.getLocalTempDir(), "posteriorProbs.txt")
        system("echo %s | cactus_realign %s %s --diagonalExpansion=10 \
        --splitMatrixBiggerThanThis=100 --outputAllPosteriorProbs=%s --loadHmm=%s" % \
                   (exonerateCigarString[:-1], tempRefFile, tempReadFile, 
                    tempPosteriorProbsFile, options.alignmentModel))
        
        #Now collate the reference position expectations
        for refPosition, queryPosition, posteriorProb in \
        map(lambda x : map(float, x.split()), open(tempPosteriorProbsFile, 'r')):
            key = (referenceSequenceName, int(refPosition))
            if key not in expectationsOfBasesAtEachPosition:
                expectationsOfBasesAtEachPosition[key] = dict(zip(BASES, [0.0]*len(BASES)))
            queryBase = querySequence[int(queryPosition)].upper()
            if queryBase in BASES: #Could be an N or other wildcard character, which we ignore
                expectationsOfBasesAtEachPosition[key][queryBase] += posteriorProb
    
    #Pickle the posterior probs
    fileHandle = open(outputPosteriorProbsFile, 'w')
    cPickle.dump(expectationsOfBasesAtEachPosition, fileHandle, cPickle.HIGHEST_PROTOCOL)
    fileHandle.close() 

def getProb(subMatrix, start, end):
    """Get the substitution probability.
    """
    return subMatrix[(start, end)]

def calcBasePosteriorProbs(baseObservations, refBase, 
                           evolutionarySubstitionMatrix, errorSubstutionMatrix):
    """Function that does the column probability calculation.
    """
    logBaseProbs = map(lambda missingBase : \
            math.log(getProb(evolutionarySubstitionMatrix, refBase.upper(), missingBase)) + 
            reduce(lambda x, y : x + y, map(lambda observedBase : \
                        math.log(getProb(errorSubstutionMatrix, missingBase, 
                                         observedBase))*baseObservations[observedBase], BASES)), BASES)
    totalLogProb = reduce(lambda x, y : x + math.log(1 + math.exp(y-x)), logBaseProbs)
    return dict(zip(BASES, map(lambda logProb : math.exp(logProb - totalLogProb), logBaseProbs)))

def loadHmmSubstitutionMatrix(hmmFile):
    """Load the substitution matrix from an HMM file
    """
    hmm = Hmm.loadHmm(hmmFile)
    m = hmm.emissions[:len(BASES)**2]
    m = map(lambda i : m[i] / sum(m[4*(i/4):4*(1 + i/4)]), range(len(m))) #Normalise m
    return dict(zip(product(BASES, BASES), m))

def getNullSubstitutionMatrix():
    """Null matrix that does nothing
    """
    return dict(zip(product(BASES, BASES), [1.0]*len(BASES)**2))

def variantCallSamFileTargetFn(target, samFile, referenceFastaFile, 
                            outputVcfFile, tempPosteriorProbFiles, options):
    """Collates the posterior probabilities and calls SNVs for each reference base.
    """
    #Hash to store posterior probabilities in
    expectationsOfBasesAtEachPosition = {}

    #Read in the posterior probs from the pickles from the tempPosteriorProbFiles files
    for tempPosteriorProbFile in tempPosteriorProbFiles:
        fileHandle = open(tempPosteriorProbFile, 'r')
        expectationsOfBasesAtEachPosition2 = cPickle.load(fileHandle)
        for key in expectationsOfBasesAtEachPosition2:
            if key not in expectationsOfBasesAtEachPosition:
                expectationsOfBasesAtEachPosition[key] = dict(zip(BASES, [0.0]*len(BASES)))
            for base in BASES:
                expectationsOfBasesAtEachPosition[key][base] += expectationsOfBasesAtEachPosition2[key][base]
        fileHandle.close()
    
    #Array to store the VCF calculations
    variantCalls = [] #Each key is of the form (referenceName, referencePosition, non-ref base, probability)
    
    #Hash of ref seq names to sequences
    refSequences = getFastaDictionary(referenceFastaFile) 
    
    #Substitution matrix modeling the difference between reads and the true reference
    errorSubstitutionMatrix = loadHmmSubstitutionMatrix(options.errorModel)
    
    #Substitution matrix modeling the difference between  the true reference and the given reference
    evolutionarySubstitutionMatrix = getNullSubstitutionMatrix() #Currently stupid
    
    #Now do the SNV calculations
    for refSeqName, refPosition in expectationsOfBasesAtEachPosition:
        refBase = refSequences[refSeqName][refPosition] #The reference base
        
        expectations = expectationsOfBasesAtEachPosition[(refSeqName, refPosition)]
        totalExpectation = sum(expectations.values())
        assert totalExpectation > 0 
        #This is the calculation of the posterior probability
        posteriorProbs = calcBasePosteriorProbs(dict(zip(BASES, map(lambda x : float(expectations[x])/totalExpectation, BASES))), refBase, 
                                                evolutionarySubstitutionMatrix, errorSubstitutionMatrix)                          
        for base in BASES:
            if base != refBase and posteriorProbs[base] >= options.threshold:
                variantCalls.append((refSeqName, refPosition, base, posteriorProbs[base]))


    #For each call write out a VCF line representing the output.
    variantCalls.sort(key=operator.itemgetter(1))
    outFile = open(outputVcfFile, "w")
    outFile.write("##fileformat=VCFv4.2\n")
    outFile.write("##fileDate=" + str(datetime.datetime.now()).replace("-", "") + "\n")
    outFile.write("##source=marginCaller\n")
    outFile.write("##reference=" + referenceFastaFile + "\n")
    outFile.write("##samFile=" + samFile + "\n")
    outFile.write("##INFO=<ID=NS,Number=1,Type=Integer,Description=marginCaller" + "\n")
    outFile.write("##INFO=<ID=AF,Number=A,Type=Float,Description=Allele Frequency>" + "\n")
    outFile.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n")
    for line in variantCalls:
        refSeqName = line[0]
        refPosition = line[1]
        refBase = refSequences[refSeqName][refPosition]
        outFile.write("\t".join([line[0], str(line[1]), refBase, line[2], str(line[3])]))#line[0] + "\t" + str(line[1]) + "\t" + refBase + "\t" + line[2] + "\t" + str(line[3]) + "\n")
        outFile.write("\n")
    outFile.close()
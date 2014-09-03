from nanopore.metaAnalyses.abstractMetaAnalysis import AbstractMetaAnalysis
from sonLib.bioio import system
import os, sys, glob

class Fastaseq():
	"""
	fasta reader
	"""
	def __init__(self):
		self.id = None
		self.seq = ''
		self.length = ''
	  
	@staticmethod 
	def readline(linein):
		seqobj = Fastaseq()
		for line in linein:
			if len(line)==0: 
				print >> sys.stderr, 'empty line'
				continue
			if line.startswith('>'):
				if seqobj.id is None:
					seqobj.id = line.rstrip()
					continue
				else:
					yield seqobj
					seqobj = Fastaseq()
					seqobj.id = line.rstrip()
			else:
				seqobj.seq += line.rstrip('\n\r').upper()
		yield seqobj

class CustomTrackAssemblyHub(AbstractMetaAnalysis):
	"""moves mapping.sorted.bam and mapping.sorted.bam.bai files to a folder and creates trackDb.txt"""
	def __init__(self, outputDir, experiments):
		AbstractMetaAnalysis.__init__(self, outputDir, experiments)
		parentFolder = "/hive/users/miten/for_public_html/myhub/"

		experiments = []
		for readFastqFile, readType, referenceFastaFile, mapper, analyses, resultsDir in self.experiments:
			experiment = resultsDir.split("/")[-1]
			experiments.append(experiment)
			hubFastaDir = experiment.split(".fastq")[-1].split(".fasta")[0][1:]
			outFolderReferenceFiles = parentFolder + hubFastaDir + "/"
			outFolderBamFiles = outFolderReferenceFiles + "bamFiles/"

			# Create hierarchical reference and bamfile folders
			if not os.path.exists(outFolderReferenceFiles):
				os.mkdir(outFolderReferenceFiles)
			if not os.path.exists(outFolderBamFiles):
				os.mkdir(outFolderBamFiles)

			system("cp %s %s" % (os.path.join(resultsDir, "mapping.sorted.bam"), outFolderBamFiles + experiment + ".sorted.bam"))
			system("cp %s %s" % (os.path.join(resultsDir, "mapping.sorted.bam.bai"), outFolderBamFiles + experiment + ".sorted.bam.bai"))

		genomes = open(parentFolder + "genomes.txt", "a")
		for referenceFastaFile in self.referenceFastaFiles:
			if referenceFastaFile.endswith(".fa") or referenceFastaFile.endswith(".fasta"):
				header = referenceFastaFile.split("/")[-1].split(".fasta")[0]
				system("cp %s %s" % (referenceFastaFile, parentFolder + header + "/"))

				# Create 2bit referenceFastaFile
				newreferenceFastaFile = parentFolder + header + "/" + header + ".fasta"
				ref2bit = newreferenceFastaFile.split(".fa")[0] + ".2bit"
				system("/cluster/bin/x86_64/faToTwoBit %s %s" % (newreferenceFastaFile, ref2bit))
				
				# Get reference length for coordinates
				fastaFile = open(referenceFastaFile, "r")
				for seq in Fastaseq.readline(fastaFile):
					id = seq.id.split(" ")[0].replace(">", "")
					coord = len(seq.seq)
				fastaFile.close()
				
				# Fasta referenceFastaFile name without .fasta
				genomes.write("genome " + header + "\n")
				genomes.write("trackDb " + header + "/trackDb.txt\n")
				genomes.write("groups groups.txt\n")
				genomes.write("description " + header + "\n")
				genomes.write("twoBitPath " + header + "/" + header + ".2bit\n")
				genomes.write("organism " + header + "\n")
				genomes.write("defaultPos " + id + ":1-" + str(coord) + "\n")
				genomes.write("\n")

		for experiment in experiments:
			hubFastaDir = experiment.split(".fastq")[-1].split(".fasta")[0][1:]
			tracks = open(parentFolder + hubFastaDir + "/trackDb.txt", "a")
			label = experiment.split(".fastq")[0].split("_")[-1]
			readType = experiment.split(".fastq")[0].split("_")[-1]
			tracks.write("track " + readType + "_\n")
			tracks.write("longLabel " + experiment + "\n")
			tracks.write("shortLabel " + readType + "\n")
			tracks.write("priority 10\n")
			tracks.write("visibility pack\n")
			tracks.write("colorByStrand 150,100,30 230,170,40\n")
			tracks.write("color 150,100,30\n")
			tracks.write("altColor 230,170,40\n")
			tracks.write("bigDataUrl bamFiles/" + experiment + ".sorted.bam\n")
			tracks.write("type bam\n")
			tracks.write("group " + readType + "\n")
			tracks.write("html assembly\n\n")
		tracks.close()

		genomes.close()

		groups = open(parentFolder + "groups.txt", "a")
		groups.write("name readType\n")
		groups.write("label readType\n")
		groups.write("priority 1\n")
		groups.write("defaultIsClosed 0\n\n")
		groups.close()
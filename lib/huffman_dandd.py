#import parallel
#import random
#import pandas as pd
from ast import Str
from numpy import unique
import sys
import os
import pickle
import hashlib
import warnings
import re
import subprocess
import csv
from multiprocessing import Process
#import math
#import glob

DASHINGLOC="/home/jbonnie1/lib/dashing/dashing"
codelib='/home/jbonnie1/scr16_blangme2/jessica/dandd/dev-dandD/lib/'

class SpeciesSpecifics:
    '''An object to store the specifics of a species file info'''
    def __init__(self, tag: str, genomedir: str, sketchdir: str, kstart: int):
        self.tag=tag
        self.sketchdir=os.path.join(sketchdir, tag)
        os.makedirs(self.sketchdir, exist_ok=True)
        self.species=self._resolve_species()
        self.hashkey=self._read_hashkey()
        self.cardkey=self._read_cardkey()
        self.inputdir=self._locate_input(genomedir)
        self.card0 = []
        self.kstart = kstart
        
    def _read_hashkey(self):
        usual=os.path.join(self.sketchdir,self.tag+'_hashkey.pickle')
        if os.path.exists(usual):
            hashkey=pickle.load(open(usual, "rb", -1))
        else:
            hashkey=dict()
        return hashkey

    def save_hashkey(self):
        usual=os.path.join(self.sketchdir,self.tag+'_hashkey.pickle')
        with open(usual,"wb") as f:
            pickle.dump(file=f, obj=self.hashkey)
    
    def _read_cardkey(self):
        usual=os.path.join(self.sketchdir, self.tag+'_cardinalities.pickle')
        if os.path.exists(usual):
            cardkey=pickle.load(open(usual, "rb", -1))
        else:
            cardkey=dict()
        return cardkey
    
    def save_cardkey(self):
        usual=os.path.join(self.sketchdir, self.tag+'_cardinalities.pickle')
        with open(usual,"wb") as f:
            pickle.dump(file=f, obj=self.cardkey)
            
    def _resolve_species(self):
        for title in ['HVSVC2','ecoli','salmonella','human']:
            if title in self.tag:
                return title
        os.warnings("FOR SOME REASON I DON'T RECOGNIZE THAT SPECIES TAG!!!")
        return self.tag
    
    def _locate_input(self, genomedir: str):
        if self.species == 'HVSVC2':
            return os.path.join(genomedir, self.species, self.tag.replace('HVSVC2','consensus'))
        else:
            return os.path.join(genomedir, self.tag)
        
    def check_cardinality(self, fullpath):
        if fullpath in self.cardkey.keys() and self.cardkey[fullpath] != 0:
            return float(self.cardkey[fullpath])
        elif fullpath not in self.card0:
            self.card0.append(fullpath)
        return 0
    

class SketchFilePath:
    '''An object to prepare sketch and union naming and directory location'''
    def __init__(self, filenames: list, kval: int, registers: int, speciesinfo: SpeciesSpecifics, prefix=None):
        self.files = filenames
        self.ngen = len(filenames)
        self.base = self.nameSketch(speciesinfo=speciesinfo, kval=kval, registers=registers)
        self.dir = os.path.join(speciesinfo.sketchdir,"k"+ str(kval), "ngen" + str(self.ngen))
        self.full = os.path.join(self.dir, self.base)
        self.registers = registers
        os.makedirs(self.dir, exist_ok=True) 
    
    def assign_hash_string(self, filename: str, speciesinfo: SpeciesSpecifics, length: int):
        if filename in speciesinfo.hashkey.keys():
            return speciesinfo.hashkey[filename]
        else:
            alphanum=hashlib.md5(filename.encode()).hexdigest()
            trunc=alphanum[:length]
            if trunc in speciesinfo.hashkey.values():
                warnings.warn("Hashvalue " + trunc + " has 2 keys!! " + filename + " will be assigned to a longer hash.")
                return self.assign_hash_string(filename, speciesinfo, length=length+1)
            else:
                speciesinfo.hashkey[filename] = trunc
                return trunc
    
    def nameSketch(self, speciesinfo: SpeciesSpecifics, kval: int, registers: int):
        #print("inside namesketch")
        #print("ngen value is: {0}".format(self.ngen))
        if self.ngen > 1:
            
            filehashes = [self.assign_hash_string(filename=onefile, speciesinfo=speciesinfo, length=1) for onefile in self.files]
            filehashes.sort()
            outfile = speciesinfo.tag + "_" + "_".join(filehashes) + "_k" + str(kval) + "_r" + str(registers) + ".hll"
        else:
            outfile=os.path.basename(self.files[0]) + ".w." + str(kval) + ".spacing." + str(registers) + ".hll"
        return outfile    

    def check_cardinality(self, speciesinfo: SpeciesSpecifics):
        if self.full in speciesinfo.cardkey.keys() and speciesinfo.cardkey[self.full] != 0:
            return float(speciesinfo.cardkey[self.full])
        else:
            speciesinfo.card0.append(self.full)
            return 0


class SketchObj:
    ''' A sketchobject.
        kval = the kvalue used to construct the sketch
        sketch = the location of the sketch file
        cmd = the command used to create the sketch
        card = the cardinality of the sketch
        
        Inputs:
        kval:
        sfp: SketchFilePath object
        registers: number of registers to tell dashing to use
        speciesinfo: SpeciesSpecifics object containing path information for the species/tag
        presketches: list of sketches to use in union sketching
    '''
    
    def __init__(self, kval, sfp, speciesinfo, presketches=None):
        self.kval = kval
        self.sketch = None
        self.cmd = None
        self._sfp = sfp
        #self._registers = registers
        self._presketches = presketches
        #self._speciesinfo = speciesinfo
        self.create_sketch(sfp, speciesinfo)
        self.card = self.check_cardinality(speciesinfo)
        self.dpos = self.card/self.kval
    
    def __lt__(self, other):
        # lt = less than
        return self.dpos < other.dpos
    def __gt__(self, other):
        # gt = greater than
        return self.dpos > other.dpos
    
    #if (! file.exists(sketch_loc) | file.size(sketch_loc) == 0L){
    #    command=paste0("seq ", kval," ", maxk, " | parallel --jobs 8 '~/lib/dashing/dashing sketch -k {} -p ", parval," --prefix ", sketchdir,"/k{}/ngen1 " ," -S ",nregister," " ,file.path(genomedir, fname),"'")
    def leaf_sketch(self, sfp, speciesinfo):
        ''' If leaf sketch file exists, record the command that would have been used.
            If not run the command and store it.'''
        cmdlist = [DASHINGLOC, "sketch", "-k" + str(self.kval),
                   "-S",str(sfp.registers),
                   "-p10","--prefix", str(sfp.dir),
                   os.path.join(speciesinfo.inputdir, sfp.files[0])]
        cmd = " ".join(cmdlist)
        print(cmd)
        if (not os.path.exists(sfp.full)) or os.stat(sfp.full).st_size == 0:
            print("The sketch file {0} either doesn't exist or is empty".format(sfp.full))
            subprocess.call(cmd, shell=True)
            self.cmd=cmd
            ##TODO Check if call raises error / returns 0
        else:
            self.cmd = cmd
        #print(self.cmd)
    #unionprefix <- file.path(sketchkndir,nameSketch(reorder[1:g], kval,registers=nregister))
     #command <- paste0("~/lib/dashing/dashing union -p ", parval," -z -o ", unionprefix, " ", alt_input1, " ", alt_input2)
        #print(command)
        #if (! file.exists(unionprefix) | file.size(unionprefix) == 0L){
        #  system(command, ignore.stdout = FALSE)
        #} 
        #sketch_call=subprocess.run([ "-p10","-o", str(sketchloc), left_sketch, right_sketch])
        #print(sketch_call)
    def union_sketch(self, sfp):
        ''' If union sketch file exists, record the command that would have been used.
            If not run the command and store it.'''
        cmdlist = [DASHINGLOC, "union", "-p 10 ","-z -o", str(sfp.full)] + self._presketches
        cmd = " ".join(cmdlist)
        #print(cmd)
        #print("SIZE of {0} is {1}".format(self._sfp.full, os.stat(sfp.full)))
        if (not os.path.exists(sfp.full)) or os.stat(sfp.full).st_size == 0:
            print("The sketch file {0} either doesn't exist or is empty".format(sfp.full))
            #self.cmd=subprocess.run(cmdlist)
            subprocess.call(cmd, shell=True)
            self.cmd=cmd
        else:
            self.cmd = cmd
            #" ".join(cmdlist)
        print(self.cmd)
    ##TODO: make leaf sketch and union sketch private
        
    def create_sketch(self, sfp: SketchFilePath, speciesinfo: SpeciesSpecifics):
        ''' If sketch file exists, assign path to self.sketch and return path. 
            If not create sketch, assign, and then return path.'''
        #self.sketch = self._sfp.full
        if sfp.ngen == 1:
            self.leaf_sketch(sfp, speciesinfo)
        elif sfp.ngen > 1:
            self.union_sketch(sfp)
        else:
            ##TODO: Raise runtime error raise RuntimeError(string with warning)
            print("For some reason you are trying to sketch an empty list of files. Don't do that.")
            sys.exit()
        self.sketch = sfp.full
        return self.sketch
    
    def print(self):
        ##TODO make this a __repr__ function instead
        print("k : {0}; cardinality: {1}; pos delta: {2}; loc : {3}; cmd: {4}".format(self.kval, self.card, self.dpos, self.sketch, self.cmd))
    
    def individual_card(self, speciesinfo):
        cmdlist = [DASHINGLOC,"card --presketched -p10"] +  [self.sketch]
        cmd = " ".join(cmdlist)
        #print(cmd)
        card_lines=subprocess.Popen(cmd,shell=True,stdout=subprocess.PIPE,text=True).stdout.readlines()
        for card in csv.DictReader(card_lines, delimiter='\t'):
            speciesinfo.cardkey[card['#Path']] = card['Size (est.)']
            
    def check_cardinality(self, speciesinfo: SpeciesSpecifics):
        if self._sfp.full not in speciesinfo.cardkey.keys() or speciesinfo.cardkey[self._sfp.full] == 0:
            self.individual_card(speciesinfo)     
        return float(speciesinfo.cardkey[self.sketch])

        #else:
        #    self.individual_card(speciesinfo)
        #return float(speciesinfo.cardkey[self._sfp.full])
  
class DeltaTreeNode:
    ''' A node in a Delta tree. 
        symbol = name of input file or composite of inputfiles
        progeny = list of leaf nodes decended from the node
        left = left child of non-leaf union nodes
        right = right child of non-leaf union nodes
        ngen = the number of genomes in the sketches for the node
        '''
    def __init__(self, fasta_input, left, right, progeny=None ):
        self.fasta_input = fasta_input
        self.progeny = progeny
        self.left = left
        self.right = right
        self.mink = 0
        self.maxk = 0
        self.bestk = 0
        self.delta = 0
        self.ksketches = [None] * 25
        self.assign_progeny()
        self.fastas = [f.fasta_input for f in self.progeny]
        self.ngen = len(self.progeny)
        #self.speciesinfo=speciesinfo

    def __repr__(self):
        return f"['{self.fasta_input}', k: {self.bestk}, delta: {self.delta}, ngen: {self.ngen} ]"
        
    def __lt__(self, other):
        # lt = less than
        return self.ngen < other.ngen
    def is_leaf(self):
        if self.right or self.left:
            return False
        else:
            return True
    
    def assign_progeny(self):
        '''something'''
        if not self.progeny:
            self.progeny=[self]
            
#    def batch_update_card(self, card0, cards):
#        cmdlist = [DASHINGLOC,"card --presketched -p10"] +  card0
#        cmd = " ".join(cmdlist)
#        card_lines=subprocess.Popen(cmd,shell=True,stdout=subprocess.PIPE,text=True).stdout.readlines()
#        for card in csv.DictReader(card_lines, delimiter='\t'):
#            cards[card['#Path']] = card['Size (est.)']
#        return cards
    def find_delta_helper(self, speciesinfo, registers, kval, direction=1):
        '''something'''
        self.update_node(speciesinfo, registers, kval)
        if direction < 0:
            self.mink = kval
        else:
            self.maxk = kval
        old_d = self.delta
        new_d = self.ksketches[kval].dpos
        if old_d < new_d:
            speciesinfo.kstart = kval
            self.bestk = kval
            self.delta = new_d
            self.find_delta_helper(speciesinfo, registers, kval+direction, direction)
        return
    
    def find_delta(self, speciesinfo, registers, kval):
        '''something'''
        self.find_delta_helper(speciesinfo, registers, kval, direction=1)
        self.find_delta_helper(speciesinfo, registers, kval, direction=-1)
        return

    def update_node(self, speciesinfo, registers, kval):
        '''Populate the sketch object for the given k at the self node as well as all children of the node'''
        if self.ksketches[kval] is None:
            #create sketch file path holding information relating to the sketch for that k 
            sfp = SketchFilePath(filenames=self.fastas, kval=kval, registers = registers, speciesinfo=speciesinfo)
            if self.ngen > 1:
                self.right.update_node(speciesinfo, registers, kval)
                self.left.update_node(speciesinfo, registers, kval)
                self.ksketches[kval] = SketchObj(kval = kval, sfp = sfp, speciesinfo=speciesinfo, presketches=[self.left.ksketches[kval].sketch, self.right.ksketches[kval].sketch])
                #print([self.left.ksketches[kval].sketch,self.right.ksketches[kval].sketch])
            elif self.ngen == 1:
                print("Inside ngen=1 of update_node")
                self.ksketches[kval] = SketchObj(kval = kval, sfp = sfp,  speciesinfo=speciesinfo)
                self.update_card(speciesinfo)
            else:
                print("For some reason you are trying to sketch ngen that is not >= 1. Something is amiss.")
                sys.exit()
        self.update_card(speciesinfo)
        return
    def update_card(self, speciesinfo):
        '''something'''
        sketches = [sketch for sketch in self.ksketches if sketch is not None]
        cardlist = [sketch.sketch for sketch in sketches if sketch.card == 0]
        if len(cardlist) > 0:
            cmdlist = [DASHINGLOC,"card --presketched -p10"] +  cardlist
            cmd = " ".join(cmdlist)
            print(cmd)
            card_lines=subprocess.Popen(cmd,shell=True,stdout=subprocess.PIPE,text=True).stdout.readlines()
            for card in csv.DictReader(card_lines, delimiter='\t'):
                speciesinfo.cardkey[card['#Path']] = card['Size (est.)']
        #print(self._speciesinfo.cardkey)
        for sketch in self.ksketches:
            if sketch:
                if sketch.sketch in sketches:
                    sketch.check_cardinality(speciesinfo)
                    sketch.dpos=sketch.card/sketch.kval


class DeltaTree:
    ''' Delta tree data structure. '''
    def __init__(self, fasta_files, speciesinfo, kstart=10, registers=20):
        self.hashkey = speciesinfo.hashkey
        #self.files = self.fasta_files(speciesinfo.inputdir)
        self.codebook = {}
        self._code_lengths = []
        self._symbols = []
        self._code_words = []
        self.mink=0
        self.maxk=0
        #self._speciesinfo=speciesinfo
        self.kstart=kstart
        self.registers=registers
        self._build_tree(fasta_files, speciesinfo)
        self.fill_tree(speciesinfo, registers)
        self.ngen = len(fasta_files)
        #self.card0 = speciesinfo.card0
        #self.cardkey=speciesinfo.cardkey
    # def fasta_files(inputdir):
    #     '''Retrieve sorted list of fasta files in the given directory'''
    #     reg_compile = re.compile(inputdir + "/*\.(fa.gz|fasta.gz|fna.gz|fasta|fa)")
    #     return [fasta for fasta in os.listdir(inputdir) if reg_compile].sort()
    def batch_update_card(self, speciesinfo):
        '''Update the cardinality dictionary for any sketches which have been added to the card0 list in speciesinfo '''
        if len(speciesinfo.card0) > 0:
            cmdlist = [DASHINGLOC,"card --presketched -p10"] +  speciesinfo.card0
            cmd = " ".join(cmdlist)
            print(cmd)
            card_lines=subprocess.Popen(cmd,shell=True,stdout=subprocess.PIPE,text=True).stdout.readlines()
            for card in csv.DictReader(card_lines, delimiter='\t'):
                speciesinfo.cardkey[card['#Path']] = card['Size (est.)']
            #print(speciesinfo.cardkey)
            for node in self._dt:
                for sketch in node.ksketches:
                    if sketch:
                        if sketch.sketch in speciesinfo.card0:
                            sketch.card=speciesinfo.check_cardinality(sketch.sketch)
                            sketch.dpos=sketch.card/sketch.kval
            speciesinfo.card0 = []
    
    def _build_tree(self, symbol: list, speciesinfo: SpeciesSpecifics) -> None:
        '''
        Build a DeltaTree.

        Update a list `self._dt` of DeltaTreeNodes using Algorithm 2.2 in CDS.
        Here `self._dt` corresponds to `L` in Algorithm 2.2. In the textbook, 
        a linked list data structure is used. For simplicity, we use a Python list in DeltaTree. 
        Below, we show an example to illustrate the difference when inserting a new node 
        between node[3] and node[4]:
        * Linked list:
            ```
            new_node.next = node[4]
            node[3].next = new_node
            ```
        * Python list:
            ```
            list = list[:3+1] + [new_node] + list[3+1:]
            ```

        Inputs:
            - symbol: a list of fasta files (str)
        '''
        inputs = [
            DeltaTreeNode(
                fasta_input=s, left=None, right=None
            ) for s in symbol]
        inputs.sort()
        for n in inputs:
            n.find_delta(speciesinfo, self.registers, speciesinfo.kstart)
        #inputs = [n.find_delta(speciesinfo, self.registers, speciesinfo.kstart) for n in inputs]
        # procs = []
        # for dnode in inputs:
        #     proc = Process(target=DeltaTreeNode.find_delta, args=[dnode, speciesinfo, self.registers, speciesinfo.kstart])
        #     procs.append(proc)
        #     proc.start()
        # for proc in procs:
        #     proc.join()
        
        self._dt = inputs
             
        idx_insert = 0
        idx_current = 0
        while idx_current != len(self._dt) - 1:
            new_node = DeltaTreeNode(
                fasta_input=f'{self._dt[idx_current].fasta_input}_{self._dt[idx_current+1].fasta_input}',
                progeny=self._dt[idx_current].progeny+self._dt[idx_current+1].progeny,
                #ngen=self._dt[idx_current].ngen+self._dt[idx_current+1].ngen,
                left=self._dt[idx_current],
                right=self._dt[idx_current+1]
            )
            new_node.find_delta(speciesinfo=speciesinfo, registers=self.registers, kval=speciesinfo.kstart)
            
            while idx_insert < len(self._dt)-1 and self._dt[idx_insert+1].ngen <= new_node.ngen:
                idx_insert += 1
            self._dt = self._dt[:idx_insert+1] + [new_node] + self._dt[idx_insert+1:]
            idx_current += 2
        #self.batch_update_card()
        self.compute_code()
    
    def _traverse_tree(self, node, depth, code):
        ''' Traverse a DeltaTree recursively. '''
        if node.left:
            self._traverse_tree(node.left, depth + 1, code+'0')
        if node.right:
            self._traverse_tree(node.right, depth + 1, code+'1')
        if not (node.left or node.right):
            self._code_lengths.append(depth)
            self._code_words.append(code)
            self._symbols.append(node.fasta_input)
            
    def compute_code(self) -> None:
        ''' Update symbols/code-lengths/code-words from left to right after DeltaTree is built.'''
        root = self._dt[-1]
        self._traverse_tree(root, depth=0, code='')
        for i, s in enumerate(self._symbols):
            self.codebook[s] = self._code_words[i]
        # print(self._code_lengths)
        # print(self._code_words)
        # print(self._symbols)
    
    def get_code(self, c: str) -> str:
        return self.codebook[c]
    
    def print_tree(self) -> None:
        ''' Traverse the DeltaTree in a depth-first way.'''
        root = self._dt[-1]
        print(root)
        def _print_tree_recursive(node) -> None:
            if node.left:
                print('Left', node.left)
                _print_tree_recursive(node.left)
            if node.right:
                print('Right', node.right)
                _print_tree_recursive(node.right)
        _print_tree_recursive(root)

    def print_list(self) -> None:
        nodes = []
        for i, node in enumerate(self._dt):
            nodes.append(f'\'{node.fasta_input}\'({node.ngen}\'({" ".join([i.fasta_input for i in node.progeny])})')
        print(' -> '.join(nodes))

    def fill_tree(self, speciesinfo, registers):
        '''Starting at the root make sure that all nodes in the tree contain the sketches for the argmax ks for every node as well as 2 less than the minimum and 2 greater than the maximum'''
        root = self._dt[-1]
        bestks = list(unique([n.bestk for n in self._dt]))
        bestks = [k for k in bestks if k!=0  ]
        print(bestks)
        bestks.sort()
        print(bestks)
        bestks = bestks + [bestks[0]-1] + [bestks[0]-2] + [bestks[-1]+1] + [bestks[-1]+2]
        print(bestks)
        for k in bestks:
            root.update_node( speciesinfo, registers, k)
        
def fasta_files(inputdir):
    '''return a list of all fasta files in a directory accounting for all the possible extensions'''
    reg_compile = re.compile(inputdir + "/*\.(fa.gz|fasta.gz|fna.gz|fasta|fa)")
    return [fasta for fasta in os.listdir(inputdir) if reg_compile]

def create_delta_tree(tag: str, genomedir: str, sketchdir: str, kstart: int, flist_loc=None):
    '''Given a species tag and a starting k value retrieve a list of fasta files to create a tree with the single fasta sketches populating the leaf nodes and the higher level nodes populated by unions'''
    # create a SpeciesSpecifics object that will tell us where the input files can be found and keep track of where the output files should be written
    speciesinfo = SpeciesSpecifics(tag=tag, genomedir=genomedir, sketchdir=sketchdir, kstart=kstart)
    #inputdir = speciesinfo.inputdir
    fastas = fasta_files(speciesinfo.inputdir)
    # If a fasta file list is provided subset the fastas from the species directory to only use the intersection
    if flist_loc:
        with open(flist_loc) as file:
            fsublist = [line.strip() for line in file]
        fastas = [f for f in fastas if f in fsublist]
    fastas.sort()
    dtree = DeltaTree(fasta_files=fastas,speciesinfo=speciesinfo)
    # Save the cardinality keys as well as the hashkey for the next run of the species
    speciesinfo.save_cardkey()
    speciesinfo.save_hashkey()
    dtree.print_tree()
    return dtree

def save_dtree(dtree: DeltaTree, outloc: str, tag: str, label=None):
    '''something'''
    if label is None:
        label = ""
    filepath=os.path.join(outloc,  tag + label + "_" + str(dtree.ngen) + '_dtree.pickle')
    with open(filepath,"wb") as f:
        pickle.dump(obj=dtree, file=f)
    
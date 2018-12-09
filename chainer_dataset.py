'''
    Dataset for shapenet part segmentaion.
'''
# -*- coding: utf-8 -*-

import os
import os.path
import json
import numpy as np
import sys
import chainer
import provider
import h5py
import encoding_and_decoding as ed
from distutils.util import strtobool
import argparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class ChainerDataset(chainer.dataset.DatasetMixin):
    def __init__(self, root, num_point=1024, classification=True, class_choice=None, split='train', normalize=True, augment=False, use_h5=False):
        self.root = root
        self.num_point = num_point
        self.classification = classification
        self.class_choice = class_choice
        self.split = split
        self.normalize = normalize
        self.augment = augment
        self.use_h5 = use_h5
        self.catfile = os.path.join(self.root, 'synsetoffset2category.txt')
        self.cat = {}
        self.lenght = 0
        self.class_name = {}
        self.class_number = {}

        if use_h5:
            self.use_h5file()
        else:
            self.use_default()

        #self.data is input values.
        #print(self.data)
        #print(self.data.shape)
        #self.label is labels.
        #print(self.label)
        #print(self.label.shape)
        #self.class_number convert class name to class number.
        #print(self.class_number)
        #print(len(self.class_number))
        #self.class_number convert class number to class name.
        #print(self.class_name)
        #print(len(self.class_name))
    
    # seg label is unsupported.
    def use_h5file(self):
        data = ed.decoding_hdf5_to_data(file_name=self.root)
        for d,i in zip(data,range(len(data))):
            if i == 0:
                self.data = np.array(data[d])
            else:
                self.data = np.append(self.data, data[d], axis=0)
            if self.classification:
                if i == 0:
                    self.label = np.full(len(data[d]),i,dtype=int)
                else:
                    self.label = np.append(self.label, np.full(len(data[d]),i,dtype=int), axis=0)
            else:
                self.label = 0

            self.class_name[i] = d
            self.class_number[d] = i        

    def use_default(self):
        #allocate data directory divided by classes to self.cat 
        with open(self.catfile, 'r') as f:
            for line in f:
                ls = line.strip().split()
                self.cat[ls[0]] = ls[1]
        if self.class_choice is not None:
            self.cat = {k: v for k, v in self.cat.items() if k in self.class_choice}

        self.meta = {}
        #allocate files name except extension to XX_ids
        with open(os.path.join(self.root, 'train_test_split', 'shuffled_train_file_list.json'), 'r') as f:
            train_ids = set([str(d.split('/')[2]) for d in json.load(f)])
        with open(os.path.join(self.root, 'train_test_split', 'shuffled_val_file_list.json'), 'r') as f:
            val_ids = set([str(d.split('/')[2]) for d in json.load(f)])
        with open(os.path.join(self.root, 'train_test_split', 'shuffled_test_file_list.json'), 'r') as f:
            test_ids = set([str(d.split('/')[2]) for d in json.load(f)])

        #allocate file length
        count_label = 0
        # allocate each class length
        clasees_length = {}
        #print(self.cat)
        #example:{'Car': '02958343', 'Guitar': '03467517'} number is folder mame.
        for item in self.cat:
            self.meta[item] = []
            dir_point = os.path.join(self.root, self.cat[item], 'points')
            dir_seg = os.path.join(self.root, self.cat[item], 'points_label')
            #get filename in points folder
            fns = sorted(os.listdir(dir_point))
            if self.split == 'trainval':
                fns = [fn for fn in fns if (
                    (fn[0:-4] in train_ids) or (fn[0:-4] in val_ids))]
            elif self.split == 'train':
                fns = [fn for fn in fns if fn[0:-4] in train_ids]
            elif self.split == 'val':
                fns = [fn for fn in fns if fn[0:-4] in val_ids]
            elif self.split == 'test':
                fns = [fn for fn in fns if fn[0:-4] in test_ids]
            else:
                print('Unknown split: %s. Exiting..' % (self.split))
                exit(-1)

            for fn in fns:
                token = (os.path.splitext(os.path.basename(fn))[0])
                self.meta[item].append(
                    (os.path.join(dir_point, token + '.pts'), os.path.join(dir_seg, token + '.seg')))
            #add [class lenght, lebel number]
            clasees_length[item] = len(self.meta[item])
            self.lenght += len(self.meta[item])
            self.class_name[count_label] = item
            self.class_number[item] = count_label
            count_label+=1

        #現在は座標のみとなっている。3のこと
        #self.dataにはすべてのファイルの点群データが読み込まれる。
        #予定図:[ファイル][点群][座標]
        self.data = np.zeros(shape=(self.lenght,self.num_point,3),dtype=float)
        #self.labelはlabelデータ
        if self.classification:
            self.label = np.zeros(shape=(self.lenght),dtype=int)
        else:
            self.label = np.zeros(shape=(self.lenght,self.num_point),dtype=int)
        #allocate number to label and data
        allocation_number = 0
        for item in self.cat:
            for n in range(clasees_length[item]):
                fp = self.meta[item][n]
                #extract point set from a pts file
                point_set = np.loadtxt(fp[0]).astype(np.float32)
                #nomalize
                if self.normalize:
                    point_set = pc_normalize(point_set)
                #num_point
                seg = np.loadtxt(fp[1]).astype(np.int64) - 1
                assert len(point_set) == len(seg)
                choice = np.random.choice(len(seg), self.num_point, replace=True)
                # resample
                point_set = point_set[choice, :]
                #allocate points
                self.data[allocation_number] = point_set
                #allocate label
                if self.classification:
                    self.label[allocation_number] = self.class_number[item]
                else:
                    self.label[allocation_number] = seg[choice]
                allocation_number += 1
        #メモリ対策?
        del self.meta

    def __len__(self):
        return self.lenght

    def get_example(self, i):
        if self.augment:
            rotated_data = provider.rotate_point_cloud(
                self.data[i:i + 1, :, :])
            jittered_data = provider.jitter_point_cloud(rotated_data)
            point_data = jittered_data[0]
        else:
            point_data = self.data[i]
        point_data = np.transpose(
            point_data.astype(np.float32), (1, 0))[:, :, None]
        return point_data, self.label[i]

    def get_data(self, i):
        return self.data[i]
        
    def get_label(self, i):
        return self.label[i]
    
    def get_data_array(self):
        return self.data

def pc_normalize(pc):
    """ pc: NxC, return NxC """
    l = pc.shape[0]
    centroid = np.mean(pc, axis=0)
    pc = pc - centroid
    m = np.max(np.sqrt(np.sum(pc**2, axis=1)))
    pc = pc / m
    return pc

if __name__ == '__main__':

    parser = argparse.ArgumentParser(
        description='test_dataset')
    parser.add_argument('--use_h5', '-c', type=strtobool, default='false')
    args=parser.parse_args()

    use_h5 = args.use_h5

    if use_h5:
        d = ChainerDataset(root=os.path.join(BASE_DIR, 'point_data.h5'), classification=True, class_choice=["Guitar","Car"],use_h5=use_h5)
#        import utils.show3d_balls as show3d_balls
       #show3d_balls.showpoints(d.get_data(0), ballradius=8)
    else:
        d = ChainerDataset(root=os.path.join(BASE_DIR, 'data/shapenetcore_partanno_segmentation_benchmark_v0'), classification=True, class_choice=["Chair"])
        #d = ChainerDataset(root=os.path.join(BASE_DIR, 'data/shapenetcore_partanno_segmentation_benchmark_v0'), classification=True, class_choice=["Guitar","Car"])
        points, label = d[0]
        #print(points, label)
        import utils.show3d_balls as show3d_balls
        show3d_balls.showpoints(d.get_data(0), ballradius=8)
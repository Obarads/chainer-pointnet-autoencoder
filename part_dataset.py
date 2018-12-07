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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def rotate_point_cloud(batch_data):
    """ Randomly rotate the point clouds to augument the dataset
        rotation is per shape based along up direction
        Input:
          BxNx3 array, original batch of point clouds
        Return:
          BxNx3 array, rotated batch of point clouds
    """
    rotated_data = np.zeros(batch_data.shape, dtype=np.float32)
    for k in xrange(batch_data.shape[0]):
        rotation_angle = np.random.uniform() * 2 * np.pi
        cosval = np.cos(rotation_angle)
        sinval = np.sin(rotation_angle)
        rotation_matrix = np.array([[cosval, 0, sinval],
                                    [0, 1, 0],
                                    [-sinval, 0, cosval]])
        shape_pc = batch_data[k, ...]
        rotated_data[k, ...] = np.dot(
            shape_pc.reshape((-1, 3)), rotation_matrix)
    return rotated_data


class PartDataset():
    def __init__(self, root, npoints=2500, classification=False, class_choice=None, split='train', normalize=True):
        self.npoints = npoints
        self.root = root
        self.catfile = os.path.join(self.root, 'synsetoffset2category.txt')
        self.cat = {}

        self.classification = classification
        self.normalize = normalize

        with open(self.catfile, 'r') as f:
            for line in f:
                ls = line.strip().split()
                self.cat[ls[0]] = ls[1]
        if class_choice is not None:
            self.cat = {k: v for k, v in self.cat.items() if k in class_choice}
            # print(self.cat)

        self.meta = {}
        with open(os.path.join(self.root, 'train_test_split', 'shuffled_train_file_list.json'), 'r') as f:
            train_ids = set([str(d.split('/')[2]) for d in json.load(f)])
        with open(os.path.join(self.root, 'train_test_split', 'shuffled_val_file_list.json'), 'r') as f:
            val_ids = set([str(d.split('/')[2]) for d in json.load(f)])
        with open(os.path.join(self.root, 'train_test_split', 'shuffled_test_file_list.json'), 'r') as f:
            test_ids = set([str(d.split('/')[2]) for d in json.load(f)])
        for item in self.cat:
            self.meta[item] = []
            dir_point = os.path.join(self.root, self.cat[item], 'points')
            dir_seg = os.path.join(self.root, self.cat[item], 'points_label')
            fns = sorted(os.listdir(dir_point))
            if split == 'trainval':
                fns = [fn for fn in fns if (
                    (fn[0:-4] in train_ids) or (fn[0:-4] in val_ids))]
            elif split == 'train':
                fns = [fn for fn in fns if fn[0:-4] in train_ids]
            elif split == 'val':
                fns = [fn for fn in fns if fn[0:-4] in val_ids]
            elif split == 'test':
                fns = [fn for fn in fns if fn[0:-4] in test_ids]
            else:
                print('Unknown split: %s. Exiting..' % (split))
                exit(-1)

            for fn in fns:
                token = (os.path.splitext(os.path.basename(fn))[0])
                self.meta[item].append(
                    (os.path.join(dir_point, token + '.pts'), os.path.join(dir_seg, token + '.seg')))

        self.datapath = []
        for item in self.cat:
            # datapthへitem名, 通常の座標データ, パーツデータのセグメンテーションラベル
            for fn in self.meta[item]:
                self.datapath.append((item, fn[0], fn[1]))

        self.classes = dict(zip(self.cat, range(len(self.cat))))
        self.num_seg_classes = 0
        if not self.classification:
            #print(len(self.datapath)/50)
            for i in range(int(len(self.datapath)/50)):
                l = len(np.unique(np.loadtxt(
                    self.datapath[i][-1]).astype(np.uint8)))
                if l > self.num_seg_classes:
                    self.num_seg_classes = l

        self.cache = {}  # from index to (point_set, cls, seg) tuple
        self.cache_size = 18000

    def __getitem__(self, index):
        if index in self.cache:
            point_set, seg, cls = self.cache[index]
        else:
            fn = self.datapath[index]
            cls = self.classes[self.datapath[index][0]]
            cls = np.array([cls]).astype(np.int32)
            point_set = np.loadtxt(fn[1]).astype(np.float32)
            if self.normalize:
                point_set = pc_normalize(point_set)
            seg = np.loadtxt(fn[2]).astype(np.int64) - 1
            if len(self.cache) < self.cache_size:
                self.cache[index] = (point_set, seg, cls)

        choice = np.random.choice(len(seg), self.npoints, replace=True)
        # resample
        point_set = point_set[choice, :]
        seg = seg[choice]
        if self.classification:
            return point_set, cls
        else:
            return point_set, seg

    def __len__(self):
        return len(self.datapath)


class ChainerAEDataset(chainer.dataset.DatasetMixin):
    def __init__(self, d=PartDataset(root=os.path.join(BASE_DIR, 'data/shapenetcore_partanno_segmentation_benchmark_v0'), class_choice=['Guitar'], classification=True),batchsize=32):
        self.lenght = len(d)
        self.d = d
        self.batchsize = batchsize

    def __len__(self):
        ite = int(self.lenght/self.batchsize)
        return ite*self.batchsize

    def get_example(self, i):
        x, t = self.d[i]
        #print(self.d[i])
        x = np.transpose(x.astype(np.float32), (1, 0))[:, :, None]
        t = t[0]
        #print(x, len(x[0]))
        #print(t)
        assert x.dtype == np.float32
        assert t.dtype == np.int32
        return x, t

class ChainerDataset(chainer.dataset.DatasetMixin):
    def __init__(self, root, num_point=1024, classification=True, class_choice=None, split='train', normalize=True, augment=False):
        self.root = root
        self.num_point = num_point
        self.classification = classification
        self.class_choice = class_choice
        self.split = split
        self.normalize = normalize
        self.augment = augment
        self.catfile = os.path.join(self.root, 'synsetoffset2category.txt')
        self.cat = {}

        #allocate data directory divided by classes to self.cat 
        with open(self.catfile, 'r') as f:
            for line in f:
                ls = line.strip().split()
                self.cat[ls[0]] = ls[1]
        if class_choice is not None:
            self.cat = {k: v for k, v in self.cat.items() if k in class_choice}
            # print(self.cat)

        #allocate files name except extension to XX_ids
        self.meta = {}
        with open(os.path.join(self.root, 'train_test_split', 'shuffled_train_file_list.json'), 'r') as f:
            train_ids = set([str(d.split('/')[2]) for d in json.load(f)])
        with open(os.path.join(self.root, 'train_test_split', 'shuffled_val_file_list.json'), 'r') as f:
            val_ids = set([str(d.split('/')[2]) for d in json.load(f)])
        with open(os.path.join(self.root, 'train_test_split', 'shuffled_test_file_list.json'), 'r') as f:
            test_ids = set([str(d.split('/')[2]) for d in json.load(f)])

        #allocate file length
        self.class_length = {}
        self.lenght = 0
        count_label = 0
        for item in self.cat:
            self.meta[item] = []
            dir_point = os.path.join(self.root, self.cat[item], 'points')
            dir_seg = os.path.join(self.root, self.cat[item], 'points_label')
            #get filename in points folder
            fns = sorted(os.listdir(dir_point))
            if split == 'trainval':
                fns = [fn for fn in fns if (
                    (fn[0:-4] in train_ids) or (fn[0:-4] in val_ids))]
            elif split == 'train':
                fns = [fn for fn in fns if fn[0:-4] in train_ids]
            elif split == 'val':
                fns = [fn for fn in fns if fn[0:-4] in val_ids]
            elif split == 'test':
                fns = [fn for fn in fns if fn[0:-4] in test_ids]
            else:
                print('Unknown split: %s. Exiting..' % (split))
                exit(-1)

            for fn in fns:
                token = (os.path.splitext(os.path.basename(fn))[0])
                self.meta[item].append(
                    (os.path.join(dir_point, token + '.pts'), os.path.join(dir_seg, token + '.seg')))
            #add [class lenght, lebel number]
            self.class_length[item] = [len(self.meta[item]),count_label]
            self.lenght += len(self.meta[item])
            count_label+=1

        self.classes = dict(zip(self.cat, range(len(self.cat))))
        #現在は座標のみとなっている。3のこと
        #self.dataにはすべてのファイルの点群データが読み込まれる。
        #予定図:[ファイル][点群][座標]
        self.data = np.zeros(shape=(self.lenght,self.num_point,3),dtype=float)
        #self.labelはlabelデータ
        if self.classification:
            self.label = np.zeros(shape=(self.lenght),dtype=int)
        else:
            self.label = np.zeros(shape=(self.lenght,self.num_point),dtype=int)
        count_class_lenght = 0
        for item in self.cat:
            for i in range(self.class_length[item][0]):
                fp = self.meta[item][i]
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
                #allocate number to label and data
                allocation_number = i+count_class_lenght
                #allocate points
                self.data[allocation_number] = point_set
                #allocate label
                if self.classification:
                    self.label[allocation_number] = self.class_length[item][1]
                else:
                    self.label[allocation_number] = seg[choice]
            #add class lenght to adjust self.data and label 
            count_class_lenght += self.class_length[item][0]

        #メモリ対策?
        del self.meta

        #print(self.data)
        #print(self.label)

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



def pc_normalize(pc):
    """ pc: NxC, return NxC """
    l = pc.shape[0]
    centroid = np.mean(pc, axis=0)
    pc = pc - centroid
    m = np.max(np.sqrt(np.sum(pc**2, axis=1)))
    pc = pc / m
    return pc

if __name__ == '__main__':
    #d = PartDataset(root = os.path.join(BASE_DIR, 'data/shapenetcore_partanno_segmentation_benchmark_v0'), class_choice = ['Guitar'], split='trainval')
    # print(len(d))
    #import time
    #tic = time.time()
    #i = 100
    #ps, seg = d[i]
    #print (np.max(seg))
    # print(np.min(seg))
    #print(time.time() - tic)
    #print(ps.shape, type(ps), seg.shape,type(seg))
    # sys.path.append('utils')
    #import utils.show3d_balls as show3d_balls
    #show3d_balls.showpoints(ps, ballradius=8)

    #d = PartDataset(root = os.path.join(BASE_DIR, 'data/shapenetcore_partanno_segmentation_benchmark_v0'), class_choice = ['Guitar','Car'], classification = True)
    """
    d = PartDataset(root=os.path.join(BASE_DIR, 'data/shapenetcore_partanno_segmentation_benchmark_v0'),
                    class_choice=['Chair','Car'], classification=True, npoints=1024)
    # Classes are not same amount of dataset.
    d0 = ChainerAEDataset(d)
    data_point, label = d0.get_example(0)
    #print('data_point', data_point, 'label', label)
    print('data_point', data_point.shape, 'label', label)
    """

    d = ChainerDataset(root=os.path.join(BASE_DIR, 'data/shapenetcore_partanno_segmentation_benchmark_v0'), classification=True, class_choice=["Guitar","Car"])
    points, label = d[0]
    print(points, label)
    import utils.show3d_balls as show3d_balls
    show3d_balls.showpoints(d.get_data(0), ballradius=8)

    #pd, cls = d[1]
    #print("ps:{}".format(ps))
    #print("cls:{}".format(cls))
    #import utils.show3d_balls as show3d_balls
    #show3d_balls.showpoints(ps1, ballradius=8)
    #print(pd.shape, type(pd), cls.shape, type(cls))

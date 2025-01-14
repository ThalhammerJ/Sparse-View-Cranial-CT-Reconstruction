import os
import sys
import numpy as np
import random
import tensorflow as tf
from tensorflow import keras
import scipy.ndimage as nd
from tensorflow.python.keras import backend as K
import pandas as pd
import scipy.stats

class DataGen(tf.keras.utils.Sequence):

    """
    Generator Function to load data for the training/testing of the classification network. 
    For the training/validation data, it is assumed that the data is saved as three neighbouring slices
    stacked to a three channel image.
    For the test data, indiviudal images are loaded and concatenated with the neighbouring slices.
    
        
    Parameters
    ----------
    df : dataframe
        dataframe with the traing/val/test data
    path : string
        path of the directory where the data is located
    batch_size : int
        Batchsize used in the training process.
    augmentation : bool
        If data augmentation shall be applied or not.
    train : bool
        If 
    shape : size of individual output images

    Returns
    -------
    batch_sparse, batch_clean : ndarray
        Sparse-view batch, gt batch
    """
        
    def __init__(self, df = None, path = None, batch_size = None, augmentation = False, train = True, shape = (260, 260)):
        self.df_copy = df.copy()
        self.slice_id_list = self.df_copy['slice_id'].values
        self.filename_list = self.df_copy['filename'].values
        if train==True:
            random.shuffle(self.slice_id_list)
            random.shuffle(self.filename_list)
        self.df = df.copy()
        self.path = path
        self.batch_size = batch_size
        self.augmentation = augmentation
        self.train = train
        self.shape = shape
   
    def __len__(self):
         return int(len(self.slice_id_list) / self.batch_size)

    def __getitem__(self, idx):
        
        if self.train == True:
            tmp_filenames = self.filename_list[idx*self.batch_size:(idx+1)*self.batch_size]
            inpt_batch, label_batch = self.__data_gen_train(tmp_filenames)
            return inpt_batch, label_batch
        else:
            tmp_slice_ids = self.slice_id_list[idx*self.batch_size:(idx+1)*self.batch_size]
            inpt_batch, label_batch, filename_list = self.__data_gen_test(tmp_slice_ids)   
            return inpt_batch, label_batch, filename_list
    
    def load(self, path, filename):
        array = np.load(path + "/" + filename.replace('.dcm', '.npy'))
        return array

    def _augmentation(self, img):
        """
        Apply augemntations with certain probabilites specified in the individual functions.
        
        input : array
        out: array
        """
        #random rotate
        img = self.rot_90(img)
        
        #random horizontal/vertical flip
        img = self.flip(img)

        #random ereazing
        img = self.random_erasing(img)
        
        #random roll
        img = self.random_shift(img)
        return img
    
    def random_shift(self, img, prob=0.5):
        if random.uniform(0, 1) > prob:
            return img
        
        else:
            shift = (int(random.uniform(-75, 76)), int(random.uniform(-75, 76)))
            img = np.roll(img, shift, axis=(0, 1))
            return img
        
    def random_erasing(self, img, prob=0.4, lp=0.01, hp=0.3):
        if random.uniform(0, 1) > prob:
            return img
        
        else:
            ereased_area = random.uniform(lp, hp) * img.shape[0]**2
            a = int(random.uniform(1, img.shape[0]-1))
            b = int(ereased_area/a) 

            center = (int(random.uniform(a//2, img.shape[0] - a//2)), int(random.uniform(b//2, img.shape[0] - b//2)))

            img[center[0] - a//2:center[0] + a//2, center[1] - b//2:center[1] + b//2] = random.uniform(0, 255)
            return img

    def rot_90(self, img, prob=0.5):
        if random.uniform(0, 1) > prob:
            return img
        
        else:
            k = random.choice([-1, 1, 2])
            img = np.rot90(img, k=k, axes=(-2, -3))
            return img
    
    def flip(self, img, prob=0.5):
        if random.uniform(0, 1) > prob:
            return img
        else:
            horizontal_flip = np.random.choice([1, -1])
            vertical_flip = np.random.choice([1, -1])
            img = img[::horizontal_flip, ::vertical_flip]
            return img
        
    def load_img_train(self, filename):
        """
        Load training image, which is expected to have shape (260, 260, 3).
        
        input : string
        Filename of training image.
        output : array, list
        Training image with corresponding label

        """
        label = self.df.loc[self.df['filename']==filename].loc[:, 'any': 'subdural'].values
        img_cat = self.load(self.path, filename)
        return img_cat, label
        
    def load_neighbouring_slices(self, slice_id):
        """
        Load central slice with the two adjacent ones. If the slice_id is 0 or max, the central slice gets shifted by one.
        
        inputs :  int
        slice_id of central slice
        output: array, list, string
        concatenated array of three neighbouring slices, the label of the central slice, filename of central slice
        """
        index = int(slice_id.split('_')[2])
        study_uid = 'ID_' + slice_id.split('_')[1]

        df = self.df

        uid_df = df.loc[df['study_instance_uid'] == study_uid]
        if index == 0:
            index = 1
        if index == (uid_df.shape[0] -1):
            index = index-1

        filename_down = uid_df.loc[uid_df['slice_id'] == study_uid + f'_{index - 1}']['filename'].values[0]
        filename = uid_df.loc[uid_df['slice_id'] == study_uid + f'_{index}']['filename'].values[0]
        filename_up = uid_df.loc[uid_df['slice_id'] == study_uid + f'_{index + 1}']['filename'].values[0]

        image_down = self.load(self.path, filename_down)
        image_up = self.load(self.path, filename_up)
        image = self.load(self.path, filename)

        image_cat = np.concatenate([image_up[:,:,np.newaxis], image[:,:,np.newaxis], image_down[:,:,np.newaxis]], 2)
        image_cat = tf.image.resize(image_cat, [self.shape[0], self.shape[1]])
        label = uid_df.loc[uid_df['filename']==filename].loc[:, 'any': 'subdural'].values

        return image_cat, label, filename
    
    def __data_gen_test(self, tmp_slice_ids):
        """
        Generate one batch of test data.
        
        inputs : list
        Slice_ids of test data batch
        outputs : array, array
        batch of input images and batch of corresponding labels
        """
        image_list = []
        label_list = []
        filename_list = []
        
        for slice_id in tmp_slice_ids:
            try:
                image_cat, label, filename = self.load_neighbouring_slices(slice_id)
            except:
                print('cannot load slice id - substitute data with random slice')
                try:
                    slice_id = random.choice(self.slice_id_list)
                    image_cat, label, filename = self.load_neighbouring_slices(slice_id)
                except:
                    print('cannot load slice id again - substitute data with random slice')
                    slice_id = random.choice(self.slice_id_list)
                    image_cat, label, filename = self.load_neighbouring_slices(slice_id)
                    
            if self.augmentation == True:
                image_cat = self._augmentation(image_cat)

            image_list.append(image_cat)
            label_list.append(label)
            filename_list.append(filename)
            
        return np.reshape(np.array(image_list), (self.batch_size, self.shape[0], self.shape[1], 3)),\
               np.reshape(np.array(label_list), (self.batch_size, 6)),\
               filename_list
    
    def __data_gen_train(self, tmp_filenames):
        """
        Generate one batch of training data.
        
        inputs : list
        Slice_ids of train data batch
        outputs : array, array
        batch of input images and batch of corresponding labels
        """
        image_list = []
        label_list = []

        for filename in tmp_filenames:
            try:
                image_cat, label = self.load_img_train(filename)
            except:
                print('cannot load file - substitute data with random slice')
                try:
                    filename = random.choice(self.filename_list)
                    image_cat, label = self.load_img_train(filename)
                except:
                    print('cannot load file again - substitute data with random slice')
                    filename = random.choice(self.filename_list)
                    image_cat, label = self.load_img_train(filename)
            
            if self.augmentation == True:
                image_cat = self._augmentation(image_cat)
                    
            image_list.append(image_cat)
            label_list.append(label)


        return np.reshape(np.array(image_list), (self.batch_size, self.shape[0], self.shape[1], 3)),\
               np.reshape(np.array(label_list), (self.batch_size, 6)),\

    def __on_epoch_end(self):
        random.shuffle(self.slice_id_list)
        random.shuffle(self.filename_list)

def load_batch(file_list, source_dir, batchsize, shape=(256, 256), angle=128):
    """
    
    Generator function which reads in file list and returns gt and sparse-view batches. Used in the training of the U-Net.
    
    Parameters
    ----------
    file_list : list of strings
        list of file names which shall be used for training/validation/testing
    source_dir : string
        source directory where the files specified in the file list are located
    batchsize : int
        Batchsize used in the training process.
    shape : touple of ints
        Shape of individual input images. Default (256, 256)
    angle : int
        How many angles/number of projections are used in the sparse-view reconstruction.

    Returns
    -------
    batch_sparse, batch_clean : ndarray
        Sparse-view batch, gt batch
    """
    random.shuffle(file_list)
    start = 0
    end = len(file_list)
    
    while True:
        
        batch_clean = []
        batch_sparse = []
        for j in range(batchsize):
            filename = random.choice(file_list)
            
            gt_path = source_dir + f'/4096/{filename}'.replace('dcm', 'npy')
            sparse_path = source_dir + f'/{angle}/{filename}'.replace('dcm', 'npy')
            data_clean = np.load(gt_path, mmap_mode='c').astype("float32")
            data_sparse = np.load(sparse_path, mmap_mode='c').astype("float32")
            
            try:
                x = random.randrange(0, data_clean.shape[0] - shape[0])
                y = random.randrange(0, data_clean.shape[1] - shape[1])
            except:
                x = y = 0
            
            data_sparse = data_sparse[x:x+shape[0], y:y+shape[0]] 
            data_clean = data_clean[x:x+shape[0], y:y+shape[0]] 

            rot_angle = np.random.choice([0, 90, 180, 270])
            data_sparse = nd.rotate(data_sparse, rot_angle)
            data_clean = nd.rotate(data_clean, rot_angle)

            batch_clean.append(data_clean.astype('float32'))
            batch_sparse.append(data_sparse.astype('float32'))
            
        start += batchsize
        
        yield np.reshape(np.array(batch_sparse), (batchsize, shape[0], shape[1], 1)), \
              np.reshape(np.array(batch_clean), (batchsize, shape[0], shape[1], 1))

        

def loss_UNet(y_true, y_predict):
    
    #reconstruction loss
    loss_rec = K.cast(K.sum(K.square(y_predict - y_true)), dtype='float64')

    return loss_rec


def step_decay(epoch):
    """
    learning rate schedule function
    """
    epoch = epoch 
    initial_lr = 1e-4
    lr = initial_lr/(epoch+1)
    return lr





"""
The following functions are from: https://github.com/yandexdataschool/roc_comparison and implement the DeLong test in python.
"""

# AUC comparison adapted from
# https://github.com/Netflix/vmaf/
def compute_midrank(x):
    """Computes midranks.
    Args:
       x - a 1D numpy array
    Returns:
       array of midranks
    """
    J = np.argsort(x)
    Z = x[J]
    N = len(x)
    T = np.zeros(N, dtype='float')
    i = 0
    while i < N:
        j = i
        while j < N and Z[j] == Z[i]:
            j += 1
        T[i:j] = 0.5*(i + j - 1)
        i = j
    T2 = np.empty(N, dtype='float')
    # Note(kazeevn) +1 is due to Python using 0-based indexing
    # instead of 1-based in the AUC formula in the paper
    T2[J] = T + 1
    return T2


def fastDeLong(predictions_sorted_transposed, label_1_count):
    """
    The fast version of DeLong's method for computing the covariance of
    unadjusted AUC.
    Args:
       predictions_sorted_transposed: a 2D numpy.array[n_classifiers, n_examples]
          sorted such as the examples with label "1" are first
    Returns:
       (AUC value, DeLong covariance)
    Reference:
     @article{sun2014fast,
       title={Fast Implementation of DeLong's Algorithm for
              Comparing the Areas Under Correlated Receiver Operating Characteristic Curves},
       author={Xu Sun and Weichao Xu},
       journal={IEEE Signal Processing Letters},
       volume={21},
       number={11},
       pages={1389--1393},
       year={2014},
       publisher={IEEE}
     }
    """
    # Short variables are named as they are in the paper
    m = label_1_count
    n = predictions_sorted_transposed.shape[1] - m
    positive_examples = predictions_sorted_transposed[:, :m]
    negative_examples = predictions_sorted_transposed[:, m:]
    k = predictions_sorted_transposed.shape[0]

    tx = np.empty([k, m], dtype='float')
    ty = np.empty([k, n], dtype='float')
    tz = np.empty([k, m + n], dtype='float')
    for r in range(k):
        tx[r, :] = compute_midrank(positive_examples[r, :])
        ty[r, :] = compute_midrank(negative_examples[r, :])
        tz[r, :] = compute_midrank(predictions_sorted_transposed[r, :])
    aucs = tz[:, :m].sum(axis=1) / m / n - float(m + 1.0) / 2.0 / n
    v01 = (tz[:, :m] - tx[:, :]) / n
    v10 = 1.0 - (tz[:, m:] - ty[:, :]) / m
    sx = np.cov(v01)
    sy = np.cov(v10)
    delongcov = sx / m + sy / n
    return aucs, delongcov


def calc_pvalue(aucs, sigma):
    """Computes log(10) of p-values.
    Args:
       aucs: 1D array of AUCs
       sigma: AUC DeLong covariances
    Returns:
       log10(pvalue)
    """
    l = np.array([[1, -1]])
    z = np.abs(np.diff(aucs)) / np.sqrt(np.dot(np.dot(l, sigma), l.T))
    return np.log10(2) + scipy.stats.norm.logsf(z, loc=0, scale=1) / np.log(10)


def compute_ground_truth_statistics(ground_truth):
    assert np.array_equal(np.unique(ground_truth), [0, 1])
    order = (-ground_truth).argsort()
    label_1_count = int(ground_truth.sum())
    return order, label_1_count


def delong_roc_variance(ground_truth, predictions):
    """
    Computes ROC AUC variance for a single set of predictions
    Args:
       ground_truth: np.array of 0 and 1
       predictions: np.array of floats of the probability of being class 1
    """
    order, label_1_count = compute_ground_truth_statistics(ground_truth)
    predictions_sorted_transposed = predictions[np.newaxis, order]
    aucs, delongcov = fastDeLong(predictions_sorted_transposed, label_1_count)
    assert len(aucs) == 1, "There is a bug in the code, please forward this to the developers"
    return aucs[0], delongcov


def delong_roc_test(ground_truth, predictions_one, predictions_two):
    """
    Computes log(p-value) for hypothesis that two ROC AUCs are different
    Args:
       ground_truth: np.array of 0 and 1
       predictions_one: predictions of the first model,
          np.array of floats of the probability of being class 1
       predictions_two: predictions of the second model,
          np.array of floats of the probability of being class 1
    """
    order, label_1_count = compute_ground_truth_statistics(ground_truth)
    predictions_sorted_transposed = np.vstack((predictions_one, predictions_two))[:, order]
    aucs, delongcov = fastDeLong(predictions_sorted_transposed, label_1_count)
    return aucs, delongcov, calc_pvalue(aucs, delongcov)
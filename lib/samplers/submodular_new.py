import numpy as np
import time
import copy
from multiprocessing.pool import ThreadPool
from operator import itemgetter
from scipy.spatial.distance import cdist
from torch.nn.functional import normalize
from torch import Tensor

import torch
import torch.nn.functional as F

from lib.config import cfg
from sampler import Sampler
from lib.utils import log


class SubModSampler(Sampler):
    def __init__(self, model, dataset, batch_size, ltl_log_ep=5):
        super(SubModSampler, self).__init__(model, dataset)
        self.batch_size = batch_size
        self.index_set = range(0, len(self.dataset))    # It contains the indices of each image of the set.
        self.ltl_log_ep = ltl_log_ep

        penultimate_activations = torch.tensor(self.penultimate_activations)
        relu = torch.nn.ReLU(inplace=True)
        penultimate_activations = relu(penultimate_activations).numpy()

        col_sums = penultimate_activations.sum(axis=0)
        self.penultimate_activations = penultimate_activations/col_sums[np.newaxis, :]

        # p_log_p = F.softmax(f_acts, dim=1) * F.log_softmax(f_acts, dim=1)
        # H = -p_log_p.numpy()
        # self.H = np.sum(H,axis=1)                       # Compute entropy of all samples for an epoch.

    def get_subset(self, detailed_logging=False):

        set_size = len(self.index_set)
        num_of_partitions = cfg.num_of_partitions

        if set_size >= num_of_partitions*self.batch_size:
            size_of_each_part = set_size / num_of_partitions
            r_size = (size_of_each_part*self.ltl_log_ep)/self.batch_size
            partitions = [self.index_set[k:k+size_of_each_part] for k in range(0, set_size, size_of_each_part)]

            pool = ThreadPool(processes=len(partitions))
            pool_handlers = []
            for partition in partitions:
                handler = pool.apply_async(get_subset_indices, args=(partition, self.penultimate_activations, self.final_activations,
                                                self.batch_size, r_size))
                pool_handlers.append(handler)
            pool.close()
            pool.join()

            intermediate_indices = []
            for handler in pool_handlers:
                intermediate_indices.extend(handler.get())
        else:
            intermediate_indices = self.index_set

        r_size = len(intermediate_indices) / self.batch_size * self.ltl_log_ep

        if detailed_logging:
            log('\nSelected {0} items from {1} partitions: {2} items.'.format(self.batch_size, num_of_partitions, len(intermediate_indices)))
            log('Size of random sample: {}'.format(r_size))

        subset_indices = get_subset_indices(intermediate_indices, self.penultimate_activations, self.final_activations,
                                            self.batch_size, r_size)

        for item in subset_indices:     # Subset selection without replacement.
            self.index_set.remove(item)

        if detailed_logging:
            log('The selected {0} indices (second level): {1}'.format(len(subset_indices), subset_indices))
        return subset_indices


def get_subset_indices(index_set_input, penultimate_activations, final_activations,  subset_size, r_size, alpha_1=1, alpha_2=1, alpha_3=1):

    if r_size < len(index_set_input):
        index_set = np.random.choice(index_set_input, r_size, replace=False)
    else:
        index_set = copy.deepcopy(index_set_input)

    subset_indices = []     # Subset of indices. Keeping track to improve computational performance.

    class_mean = np.mean(penultimate_activations, axis=0)

    subset_size = min(subset_size, len(index_set))
    for i in range(0, subset_size):
        now = time.time()

        scores = compute_score(penultimate_activations, subset_indices, index_set)

        best_item_index = np.argmax(scores)
        subset_indices.append(index_set[best_item_index])
        index_set = np.delete(index_set, best_item_index, axis=0)

        # log('Processed: {0}/{1} exemplars. Time taken is {2} sec.'.format(i, subset_size, time.time()-now))

    return subset_indices


def compute_score(normalised_penultimate_activations, subset_indices, index_set):
    """
    :param penultimate_activations:
    :param subset_indices:
    :param index_set:
    :return: g(mu(S))
    """
    if(len(subset_indices)==0):
        return 0
    else:
        penultimate_activations_index_set =  normalised_penultimate_activations[index_set]
        subset_indices_scores = np.sum(normalised_penultimate_activations[subset_indices],axis=0)
        sum_subset_index_set = subset_indices_scores + penultimate_activations_index_set
        score_feature_wise = np.sqrt(sum_subset_index_set)
        scores = np.sum(score_feature_wise,axis=1)
        return scores

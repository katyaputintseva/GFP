import pandas as pd
import numpy as np
from matplotlib import pyplot as plt
import tensorflow as tf
import time
import os
from IPython.display import clear_output
from sklearn.model_selection import train_test_split
import matplotlib
from sklearn.preprocessing import label_binarize
from tensorflow.contrib.framework.python.ops import add_arg_scope,arg_scope


# In[4]:


def make_mutant_sq(wt_sq, mutation_list):
    '''Having a wt sequence and a list of mutations, this function combines the two into a full mutant sequence.'''
    
    mutant_sq = list(wt_sq)
    for mutation in mutation_list:
        assert mutation[0] == wt_sq[int(mutation[1:-1])+1]
        #change mutated positions in the original sequence, to obtain the mutated sequence
        mutant_sq[int(mutation[1:-1])+1] = mutation[-1]
        
    return ''.join(mutant_sq)


# In[5]:


def convert_mutants_to_arrays(f):
    
    initial_df = pd.DataFrame.from_csv(f,sep='\t',index_col=None)
    
    #extracting all the mutation combinations there are into a mutant_list 
    mutant_list = list(initial_df.aaMutations[1:])

    #separating mutation combinations into lists
    mutant_list = [[el[1:] for el in x.split(':')] for x in mutant_list]
    
    #recording the wild type sequence in order to be able to code the whole sq of mutants (and not only the mutations)
    wt_sq = 'MSKGEELFTGVVPILVELDGDVNGHKFSVSGEGEGDATYGKLTLKFICTTGKLPVPWPTLVTTLSYGVQCFSRYPDHMKQHDFFKSAMPEGYVQERTIFFKDDGNYKTRAEVKFEGDTLVNRIELKGIDFKEDGNILGHKLEYNYNSHNVYIMADKQKNGIKVNFKIRHNIEDGSVQLADHYQQNTPIGDGPVLLPDNHYLSTQSALSKDPNEKRDHMVLLEFVTAAGITHGMDELYK'
    
    #start the list with a wild-type
    mutant_sq_list = [wt_sq]

    for mutant in mutant_list:
        mutant_sq_list.append(make_mutant_sq(wt_sq, mutant))
        
    #creating the initial 0-filled carcas of unfolded versions of sqs, which will be further turned into binary matricies of shape 238 by 20 (aas)
    unfolded_df = {}

    for aa in set([item[-1] for sublist in mutant_list for item in sublist]):
        unfolded_df[aa] = np.zeros((len(initial_df),len(wt_sq)))

    #filling the binary matrices, corresponding to 20 different amino acids within the unfoded_df dict

    for ind,mutant in enumerate(mutant_sq_list):
        for pos,mut in enumerate(mutant):
            unfolded_df[mut][ind, pos] = 1.
        
    #stacking all the amino acids into one np array
    input_df = np.stack(unfolded_df.values(),axis=1)

    #putting the channel info (amino acids) to the end
    input_df = np.swapaxes(input_df,-1,-2)
    
    return initial_df, input_df, mutant_list


# In[1]:


def load_data(f, add_dist=False, dist_file='/nfs/scistore08/kondrgrp/eputints/Jupyter/mut_predictions/distances_to_chromophore.txt',
             scale=False):
    
    initial_df, input_df, mutant_list = convert_mutants_to_arrays(f)
    
    labels = initial_df.medianBrightness
    labels=labels.reshape(-1,1)

    sample_weights = initial_df.uniqueBarcodes
    sample_weights=sample_weights.reshape(-1,1)
    
    if add_dist == True:
        
        dists = pd.DataFrame.from_csv(dist_file,sep='\t')
        dists.columns=['Distance']
        
        #Adding info for positions that are not annotated (in the end of the protein and the chromophore)
        for i in range(232,240):
            dists.loc[i] = 22.088911

        for i in [65,67]:
            dists.loc[i] = 0.00
        mutation_dist_list = [100.0]

        for mutant in mutant_list:
            temp_dist_list=[]
            for mutation in mutant:
                temp_dist_list.append(dists.Distance.ix[int(mutation[1:-1])+2])
            mutation_dist_list.append(min(temp_dist_list))

        mutation_dist_list=np.array(mutation_dist_list).reshape(-1,1)    
        return initial_df, input_df, mutant_list, labels, sample_weights, mutation_dist_list
    
    else:
        return initial_df, input_df, mutant_list, labels, sample_weights


# In[10]:


# Extracting datasets to np (scipy) arrays

# import scipy.sparse

# for aa in unfolded_df:
#     print aa
#     sparse=scipy.sparse.csc_matrix(unfolded_df[aa])
#     scipy.sparse.save_npz('arrays/'+aa+'.npz', sparse)
    
# np.save('brightness.npy', labels)


# In[ ]:


xavier = tf.contrib.layers.xavier_initializer
l2_reg = tf.contrib.layers.l2_regularizer
bn = add_arg_scope(tf.layers.batch_normalization)
dense = add_arg_scope(tf.layers.dense)
conv = add_arg_scope(tf.layers.conv1d)
max_pool = add_arg_scope(tf.layers.max_pooling1d)
avg_pool = add_arg_scope(tf.layers.average_pooling1d)
dense = add_arg_scope(tf.layers.dense) 

@add_arg_scope
def residual_block(a, kernel_size, weight_decay, keep_prob=1):

    filters = a.get_shape().as_list()[-1]

    b = bn(a,name='bn_first_rb')
    b = tf.nn.relu(b)
    b = tf.nn.dropout(b, keep_prob=0.9)
    b = conv(b, filters, kernel_size=kernel_size, padding='SAME', 
             kernel_initializer=xavier(), kernel_regularizer=l2_reg(weight_decay),
            name='conv_first_rb')

    b = bn(b,name='bn_second_rb')
    b = tf.nn.relu(b)
    b = conv(b, filters, kernel_size=kernel_size, padding='SAME', 
             kernel_initializer=xavier(), kernel_regularizer=l2_reg(weight_decay),
            name='conv_second_rb')

    return a + b


# In[ ]:


@add_arg_scope
def ResNet_architecture(net, x, kernel_size, pool_size, weight_decay, keep_prob):

    temp = bn(x, name='bn_first')
    temp = conv(temp, 64, kernel_size=kernel_size, padding='SAME', 
                kernel_initializer=xavier(), kernel_regularizer=l2_reg(weight_decay),
               name='conv_first')
    temp = max_pool(inputs=temp, pool_size=pool_size, strides=2,padding='SAME')

    for scale in range(net.num_scales):
        with tf.variable_scope("scale%i" % scale):
            for rep in range(net.block_repeats):
                with tf.variable_scope("rep%i" % rep):
                    temp = residual_block(temp, kernel_size, weight_decay)

            if scale < net.num_scales - 1:
                temp = conv(temp, 2 * x.get_shape().as_list()[-1],
                         kernel_size=kernel_size, strides=2,
                         padding='SAME', name='conv_downsample', kernel_regularizer=l2_reg(weight_decay))

    temp = avg_pool(temp, pool_size=pool_size, strides=2)

    temp = bn(temp, name='bn_last')
    temp = tf.nn.relu(temp)

    temp = tf.contrib.layers.flatten(temp)

    temp = tf.nn.dropout(temp, keep_prob=keep_prob)
    temp = dense(temp,1000, activation=tf.nn.relu,name='dense_1', kernel_regularizer=l2_reg(weight_decay))
    temp = tf.nn.dropout(temp, keep_prob=keep_prob)
    temp = dense(temp,1000, activation=tf.nn.relu,name='dense_2', kernel_regularizer=l2_reg(weight_decay))
    temp = tf.nn.dropout(temp, keep_prob=keep_prob)
    temp = dense(temp,100, activation=tf.nn.relu,name='dense_3', kernel_regularizer=l2_reg(weight_decay))
    temp = tf.nn.dropout(temp, keep_prob=keep_prob)
    temp = dense(temp,1, activation=tf.nn.relu,name='dense_4', kernel_regularizer=l2_reg(weight_decay))

    return temp


# In[ ]:


def epoch_iterator(n, k):
    
    perm = np.random.permutation(n)
    
    for i in range(n / k):
        yield perm[i * k:(i + 1) * k]    


# In[ ]:


def epoch_iterator_balanced(n, batch_size, zero_share, zero_inds, nonzero_inds):
    
    for i in range(n / batch_size):
        zero_elements = np.random.choice(zero_inds,int(batch_size*zero_share))
        nonzero_elements = np.random.choice(nonzero_inds,int(batch_size*(1-zero_share)))
        
        export = np.append(zero_elements,nonzero_elements)
        np.random.shuffle(export)
        
        yield export


def reset_graph(seed=8):
    tf.reset_default_graph()
    tf.set_random_seed(seed)
    np.random.seed(seed)


def train_NN(nn_instance, input_data, patience, log_dir):
    
    print 'Initializing NN'
    
    with tf.Session() as sess:
    
        saver = tf.train.Saver()

        sess.run(nn_instance.init)
        train_mse_hist=[]
        val_mse_hist=[]
        print 'Epoch #\t\t\tTrain MSE\t\tTest MSE'
        
        for epoch in range(nn_instance.n_epoch):

            temp_train_mse = []
            temp_val_mse = []

            for idx in epoch_iterator_balanced(len(input_data.x_train), input_data.batch_size, 
                                               input_data.zero_sample_fraction, input_data.zero_inds, 
                                               input_data.nonzero_inds):

                x_batch_train = input_data.x_train[idx]
                y_batch_train = input_data.y_train[idx]
                sample_weights_batch = input_data.sample_weights_train[idx]            

                sess.run(nn_instance.train_step, {nn_instance.x_train_ph:x_batch_train,
                                                  nn_instance.y_train_ph:y_batch_train,
                                                  nn_instance.learning_rate:0.1 / (3 ** (epoch / 40)),
                                                 nn_instance.sample_weights_ph:sample_weights_batch})

                temp_train_mse.append(sess.run(nn_instance.loss, {nn_instance.x_train_ph:x_batch_train,
                                                  nn_instance.y_train_ph:y_batch_train,
                                                  nn_instance.learning_rate:0.1 / (3 ** (epoch / 40)),
                                                 nn_instance.sample_weights_ph:sample_weights_batch}))

            train_mse_hist.append(np.median(temp_train_mse))

            if epoch%10==0:

                for idx in epoch_iterator(len(input_data.x_val), input_data.batch_size):
                    x_batch_val = input_data.x_val[idx]
                    y_batch_val = input_data.y_val[idx]

                    temp_val_mse.append(sess.run(nn_instance.val_loss, {nn_instance.x_val_ph:x_batch_val,
                                                                   nn_instance.y_val_ph:y_batch_val}))

                val_mse_hist.append(np.median(temp_val_mse))

                saver.save(sess, os.path.join(log_dir, "model.ckpt"))

                print '%d\t\t\t%.2f\t\t\t%.2f' % (epoch, np.median(temp_train_mse), np.median(temp_val_mse))

            if epoch%patience==0 and epoch!=0:    
                if min(val_mse_hist[-patience:]) < np.median(temp_val_mse):
                    break
                    
    return train_mse_hist, val_mse_hist

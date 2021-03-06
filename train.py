# -*- coding: utf-8 -*-

"""

@author: alexyang

@contact: alex.yang0326@gmail.com

@file: train.py

@time: 2019/2/1 14:06

@desc:

"""

import os
import time
import re
import numpy as np
from itertools import product
from keras import optimizers

from models.keras_infersent_model import KerasInfersentModel
from models.keras_esim_model import KerasEsimModel
from models.keras_decomposable_model import KerasDecomposableAttentionModel
from models.keras_siamese_bilstm_model import KerasSimaeseBiLSTMModel
from models.keras_siamese_cnn_model import KerasSiameseCNNModel
from models.keras_iacnn_model import KerasIACNNModel
from models.tfhub_bert_model import TFHubBertModel
from models.keras_siamese_lstmcnn_model import KerasSiameseLSTMCNNModel
from models.keras_refined_ssa_model import KerasRefinedSSAModel

from config import ModelConfig, PERFORMANCE_LOG, LOG_DIR, PROCESSED_DATA_DIR, EMBEDDING_MATRIX_TEMPLATE, \
    VOCABULARY_TEMPLATE, EXTERNAL_WORD_VECTORS_FILENAME
from utils.data_loader import load_input_data
from utils.io import write_log, format_filename, pickle_load
from utils.cache import ELMoCache
from utils.data_generator import ELMoGenerator
from utils.metrics import eval_acc

os.environ['CUDA_VISIBLE_DEVICES'] = '2'


def get_optimizer(op_type, learning_rate):
    if op_type == 'sgd':
        return optimizers.SGD(learning_rate)
    elif op_type == 'rmsprop':
        return optimizers.RMSprop(learning_rate)
    elif op_type == 'adagrad':
        return optimizers.Adagrad(learning_rate)
    elif op_type == 'adadelta':
        return optimizers.Adadelta(learning_rate)
    elif op_type == 'adam':
        return optimizers.Adam(learning_rate, clipnorm=5)
    else:
        raise ValueError('Optimizer Not Understood: {}'.format(op_type))


def train_model(genre, input_level, word_embed_type, word_embed_trainable, batch_size, learning_rate,
                optimizer_type, model_name, n_epoch=50, add_features=False, scale_features=False, overwrite=False,
                lr_range_test=False, callbacks_to_add=None, eval_on_train=False, **kwargs):
    config = ModelConfig()
    config.genre = genre
    config.input_level = input_level
    config.max_len = config.word_max_len[genre] if input_level == 'word' else config.char_max_len[genre]
    config.word_embed_type = word_embed_type
    config.word_embed_trainable = word_embed_trainable
    config.callbacks_to_add = callbacks_to_add or []
    config.add_features = add_features
    config.batch_size = batch_size
    config.learning_rate = learning_rate
    config.optimizer = get_optimizer(optimizer_type, learning_rate)
    config.n_epoch = n_epoch
    config.word_embeddings = np.load(format_filename(PROCESSED_DATA_DIR, EMBEDDING_MATRIX_TEMPLATE, genre,
                                                     word_embed_type))
    vocab = pickle_load(format_filename(PROCESSED_DATA_DIR, VOCABULARY_TEMPLATE, genre, input_level))
    config.idx2token = dict((idx, token) for token, idx in vocab.items())

    # experiment name configuration
    config.exp_name = '{}_{}_{}_{}_{}_{}_{}_{}'.format(genre, model_name, input_level, word_embed_type,
                                                       'tune' if word_embed_trainable else 'fix', batch_size,
                                                       '_'.join([str(k) + '_' + str(v) for k, v in kwargs.items()]),
                                                       optimizer_type)
    if config.add_features:
        config.exp_name = config.exp_name + '_feature_scaled' if scale_features else config.exp_name + '_featured'
    if len(config.callbacks_to_add) > 0:
        callback_str = '_' + '_'.join(config.callbacks_to_add)
        callback_str = callback_str.replace('_modelcheckpoint', '').replace('_earlystopping', '')
        config.exp_name += callback_str

    input_config = kwargs['input_config'] if 'input_config' in kwargs else 'token'  # input default is word embedding
    if input_config in ['cache_elmo', 'token_combine_cache_elmo']:
        # get elmo embedding based on cache, we first get a ELMoCache instance
        if 'elmo_model_type' in kwargs:
            elmo_model_type = kwargs['elmo_model_type']
            kwargs.pop('elmo_model_type')   # we don't need it in kwargs any more
        else:
            elmo_model_type = 'allennlp'
        if 'elmo_output_mode' in kwargs:
            elmo_output_mode = kwargs['elmo_output_mode']
            kwargs.pop('elmo_output_mode')  # we don't need it in kwargs any more
        else:
            elmo_output_mode ='elmo'
        elmo_cache = ELMoCache(options_file=config.elmo_options_file, weight_file=config.elmo_weight_file,
                               cache_dir=config.cache_dir, idx2token=config.idx2token,
                               max_sentence_length=config.max_len, elmo_model_type=elmo_model_type,
                               elmo_output_mode=elmo_output_mode)
    elif input_config in ['elmo_id', 'elmo_s', 'token_combine_elmo_id', 'token_combine_elmo_s']:
        # get elmo embedding using tensorflow_hub, we must provide a tfhub_url
        kwargs['elmo_model_url'] = config.elmo_model_url

    # logger to log output of training process
    train_log = {'exp_name': config.exp_name, 'batch_size': batch_size, 'optimizer': optimizer_type, 'epoch': n_epoch,
                 'learning_rate': learning_rate, 'other_params': kwargs}

    print('Logging Info - Experiment: %s' % config.exp_name)
    if model_name == 'KerasInfersent':
        model = KerasInfersentModel(config, **kwargs)
    elif model_name == 'KerasEsim':
        model = KerasEsimModel(config, **kwargs)
    elif model_name == 'KerasDecomposable':
        model = KerasDecomposableAttentionModel(config, **kwargs)
    elif model_name == 'KerasSiameseBiLSTM':
        model = KerasSimaeseBiLSTMModel(config, **kwargs)
    elif model_name == 'KerasSiameseCNN':
        model = KerasSiameseCNNModel(config, **kwargs)
    elif model_name == 'KerasIACNN':
        model = KerasIACNNModel(config, **kwargs)
    elif model_name == 'KerasSiameseLSTMCNNModel':
        model = KerasSiameseLSTMCNNModel(config, **kwargs)
    elif model_name == 'KerasRefinedSSAModel':
        model = KerasRefinedSSAModel(config, **kwargs)
    else:
        raise ValueError('Model Name Not Understood : {}'.format(model_name))
    # model.summary()

    train_input, dev_input, test_input = None, None, None
    if lr_range_test:   # conduct lr range test to find optimal learning rate (not train model)
        train_input = load_input_data(genre, input_level, 'train', input_config, config.add_features, scale_features)
        dev_input = load_input_data(genre, input_level, 'dev', input_config, config.add_features, scale_features)
        model.lr_range_test(x_train=train_input['x'], y_train=train_input['y'], x_valid=dev_input['x'],
                            y_valid=dev_input['y'])
        return

    model_save_path = os.path.join(config.checkpoint_dir, '{}.hdf5'.format(config.exp_name))
    if not os.path.exists(model_save_path) or overwrite:
        start_time = time.time()

        if input_config in ['cache_elmo', 'token_combine_cache_elmo']:
            train_input = ELMoGenerator(genre, input_level, 'train', config.batch_size, elmo_cache,
                                        return_data=(input_config == 'token_combine_cache_elmo'),
                                        return_features=config.add_features)
            dev_input = ELMoGenerator(genre, input_level, 'dev', config.batch_size, elmo_cache,
                                      return_data=(input_config == 'token_combine_cache_elmo'),
                                      return_features=config.add_features)
            model.train_with_generator(train_input, dev_input)
        else:
            train_input = load_input_data(genre, input_level, 'train', input_config, config.add_features, scale_features)
            dev_input = load_input_data(genre, input_level, 'dev', input_config, config.add_features, scale_features)
            model.train(x_train=train_input['x'], y_train=train_input['y'], x_valid=dev_input['x'],
                        y_valid=dev_input['y'])
        elapsed_time = time.time() - start_time
        print('Logging Info - Training time: %s' % time.strftime("%H:%M:%S", time.gmtime(elapsed_time)))
        train_log['train_time'] = time.strftime("%H:%M:%S", time.gmtime(elapsed_time))

    def eval_on_data(eval_with_generator, input_data, data_type):
        model.load_best_model()
        if eval_with_generator:
            acc = model.evaluate_with_generator(generator=input_data, y=input_data.input_label)
        else:
            acc = model.evaluate(x=input_data['x'], y=input_data['y'])
        train_log['%s_acc' % data_type] = acc

        swa_type = None
        if 'swa' in config.callbacks_to_add:
            swa_type = 'swa'
        elif 'swa_clr' in config.callbacks_to_add:
            swa_type = 'swa_clr'
        if swa_type:
            print('Logging Info - %s Model' % swa_type)
            model.load_swa_model(swa_type=swa_type)
            swa_acc = model.evaluate(x=input_data['x'], y=input_data['y'])
            train_log['%s_%s_acc' % (swa_type, data_type)] = swa_acc

        ensemble_type = None
        if 'sse' in config.callbacks_to_add:
            ensemble_type = 'sse'
        elif 'fge' in config.callbacks_to_add:
            ensemble_type = 'fge'
        if ensemble_type:
            print('Logging Info - %s Ensemble Model' % ensemble_type)
            ensemble_predict = {}
            for model_file in os.listdir(config.checkpoint_dir):
                if model_file.startswith(config.exp_name+'_%s' % ensemble_type):
                    match = re.match(r'(%s_%s_)([\d+])(.hdf5)' % (config.exp_name, ensemble_type), model_file)
                    model_id = int(match.group(2))
                    model_path = os.path.join(config.checkpoint_dir, model_file)
                    print('Logging Info: Loading {} ensemble model checkpoint: {}'.format(ensemble_type, model_file))
                    model.load_model(model_path)
                    ensemble_predict[model_id] = model.predict(x=input_data['x'])
            '''
            we expect the models saved towards the end of run may have better performance than models saved earlier 
            in the run, we sort the models so that the older models ('s id) are first.
            '''
            sorted_ensemble_predict = sorted(ensemble_predict.items(), key=lambda x: x[0], reverse=True)
            model_predicts = []
            for model_id, model_predict in sorted_ensemble_predict:
                single_acc = eval_acc(model_predict, input_data['y'])
                print('Logging Info - %s_single_%d_%s Acc : %f' % (ensemble_type, model_id, data_type, single_acc))
                train_log['%s_single_%d_%s_acc' % (ensemble_type, model_id, data_type)] = single_acc

                model_predicts.append(model_predict)
                ensemble_acc = eval_acc(np.mean(np.array(model_predicts), axis=0), input_data['y'])
                print('Logging Info - %s_ensemble_%d_%s Acc : %f' % (ensemble_type, model_id, data_type, ensemble_acc))
                train_log['%s_ensemble_%d_%s_acc' % (ensemble_type, model_id, data_type)] = ensemble_acc

    if eval_on_train:
        # might take a long time
        print('Logging Info - Evaluate over train data:')
        if input_config in ['cache_elmo', 'token_combine_cache_elmo']:
            train_input = ELMoGenerator(genre, input_level, 'train', config.batch_size, elmo_cache,
                                        return_data=(input_config == 'token_combine_cache_elmo'),
                                        return_features=config.add_features, return_label=False)
            eval_on_data(eval_with_generator=True, input_data=train_input, data_type='train')
        else:
            train_input = load_input_data(genre, input_level, 'train', input_config, config.add_features, scale_features)
            eval_on_data(eval_with_generator=False, input_data=train_input, data_type='train')

    print('Logging Info - Evaluate over valid data:')
    if input_config in ['cache_elmo', 'token_combine_cache_elmo']:
        dev_input = ELMoGenerator(genre, input_level, 'dev', config.batch_size, elmo_cache,
                                  return_data=(input_config == 'token_combine_cache_elmo'),
                                  return_features=config.add_features, return_label=False)
        eval_on_data(eval_with_generator=True, input_data=dev_input, data_type='dev')
    else:
        if dev_input is None:
            dev_input = load_input_data(genre, input_level, 'dev', input_config, config.add_features, scale_features)
        eval_on_data(eval_with_generator=False, input_data=dev_input, data_type='dev')

    print('Logging Info - Evaluate over test data:')
    if input_config in ['cache_elmo', 'token_combine_cache_elmo']:
        test_input = ELMoGenerator(genre, input_level, 'test', config.batch_size, elmo_cache,
                                   return_data=(input_config == 'token_combine_cache_elmo'),
                                   return_features=config.add_features, return_label=False)
        eval_on_data(eval_with_generator=True, input_data=test_input, data_type='test')
    else:
        if test_input is None:
            test_input = load_input_data(genre, input_level, 'test', input_config, config.add_features, scale_features)
        eval_on_data(eval_with_generator=False, input_data=test_input, data_type='test')

    train_log['timestamp'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    write_log(format_filename(LOG_DIR, PERFORMANCE_LOG, genre), log=train_log, mode='a')
    return train_log


def train_bert(genre, input_level, batch_size):
    config = ModelConfig()
    config.genre = genre
    config.input_level = input_level
    config.max_len = config.word_max_len[genre] if input_level == 'word' else config.char_max_len[genre]
    config.batch_size = batch_size

    model = TFHubBertModel(config, [0, 1, 2], EXTERNAL_WORD_VECTORS_FILENAME['tfhub_bert'])

    train_input = load_input_data(genre, input_level, 'train', 'bert')
    valid_input = load_input_data(genre, input_level, 'valid', 'bert')
    test_input = load_input_data(genre, input_level, 'test', 'bert')
    model.train(train_input, valid_input)
    model.evaluate(valid_input)
    model.evaluate(test_input)


if __name__ == '__main__':
    # model_names = ['KerasInfersent', 'KerasEsim']
    # genres = ['mednli']
    # input_levels = ['word']
    # word_embed_types = ['glove_cc']
    # word_embed_trainables = [False]
    # batch_sizes = [32]
    # learning_rates = [0.001]
    # optimizer_types = ['adam']
    # input_configs = ['token_combine_elmo_id']
    # elmo_output_modes = ['elmo']
    #
    # for model_name, genre, input_level, word_embed_type, word_embed_trainable, batch_size, learning_rate, optimizer, \
    #     input_config, elmo_output_mode in product(model_names, genres, input_levels, word_embed_types,
    #                                               word_embed_trainables, batch_sizes, learning_rates, optimizer_types,
    #                                               input_configs, elmo_output_modes):
    #     if model_name == 'KerasInfersent':
    #         for encoder_type in ['bilstm_max_pool']:
    #             train_model(genre, input_level, word_embed_type, word_embed_trainable, batch_size, learning_rate,
    #                         optimizer, model_name, add_features=True, overwrite=False, eval_on_train=False,
    #                         input_config=input_config, elmo_output_mode=elmo_output_mode, encoder_type=encoder_type)
    #
    #     elif model_name == 'KerasDecomposable':
    #         for add in [True, False]:
    #             train_model(genre, input_level, word_embed_type, word_embed_trainable, batch_size, learning_rate,
    #                         optimizer, model_name, add_features=True, overwrite=False, eval_on_train=False,
    #                         input_config=input_config, elmo_output_mode=elmo_output_mode,
    #                         add_intra_sentence_attention=add)
    #     else:
    #         train_model(genre, input_level, word_embed_type, word_embed_trainable, batch_size, learning_rate, optimizer,
    #                     model_name, add_features=True, overwrite=False, eval_on_train=True, input_config=input_config,
    #                     elmo_output_mode=elmo_output_mode)

    # model_names = ['KerasInfersent', 'KerasEsim', 'KerasSiameseBiLSTM', 'KerasSiameseCNN', 'KerasSiameseLSTMCNNModel']
    # genres = ['mednli']
    # input_levels = ['word']
    # word_embed_types = ['glove_cc']
    # word_embed_trainables = [False]
    # batch_sizes = [32]
    # learning_rates = [0.001]
    # optimizer_types = ['adam']
    #
    # for model_name, genre, input_level, word_embed_type, word_embed_trainable, batch_size, learning_rate, optimizer \
    #         in product(model_names, genres, input_levels, word_embed_types, word_embed_trainables, batch_sizes,
    #                    learning_rates, optimizer_types):
    #     if model_name == 'KerasInfersent':
    #         for encoder_type in ['lstm', 'gru', 'bilstm', 'bigru', 'bilstm_max_pool', 'bilstm_mean_pool',
    #                              'self_attentive', 'h_cnn']:
    #             train_model(genre, input_level, word_embed_type, word_embed_trainable, batch_size, learning_rate,
    #                         optimizer, model_name, n_epoch=16, add_features=False, scale_features=False,
    #                         use_cyclical_lr=True, overwrite=False, eval_on_train=False, encoder_type=encoder_type)
    #     elif model_name == 'KerasDecomposable':
    #         for add in [True, False]:
    #             train_model(genre, input_level, word_embed_type, word_embed_trainable, batch_size, learning_rate,
    #                         optimizer, model_name, n_epoch=16, add_features=False, scale_features=False, overwrite=False,
    #                         use_cyclical_lr=False, eval_on_train=False, add_intra_sentence_attention=add)
    #     else:
    #         train_model(genre, input_level, word_embed_type, word_embed_trainable, batch_size, learning_rate,
    #                     optimizer, model_name, n_epoch=16, add_features=False, scale_features=False, use_cyclical_lr=True,
    #                     overwrite=False, eval_on_train=False)

    # model_names = ['KerasInfersent', 'KerasEsim', 'KerasSiameseBiLSTM', 'KerasSiameseCNN', 'KerasSiameseLSTMCNNModel']
    # genres = ['mednli']
    # input_levels = ['word']
    # word_embed_types = ['glove_cc']
    # word_embed_trainables = [False]
    # batch_sizes = [32]
    # learning_rates = [0.001]
    # optimizer_types = ['adam']
    #
    # for model_name, genre, input_level, word_embed_type, word_embed_trainable, batch_size, learning_rate, optimizer \
    #         in product(model_names, genres, input_levels, word_embed_types, word_embed_trainables, batch_sizes,
    #                    learning_rates, optimizer_types):
    #     if model_name == 'KerasInfersent':
    #         for encoder_type in ['lstm', 'gru', 'bilstm', 'bigru', 'bilstm_max_pool', 'bilstm_mean_pool',
    #                              'self_attentive', 'h_cnn']:
    #             train_model(genre, input_level, word_embed_type, word_embed_trainable, batch_size, learning_rate,
    #                         optimizer, model_name, n_epoch=50, add_features=True, scale_features=True,
    #                         use_cyclical_lr=False, overwrite=False, eval_on_train=False, encoder_type=encoder_type)
    #     elif model_name == 'KerasDecomposable':
    #         for add in [True, False]:
    #             train_model(genre, input_level, word_embed_type, word_embed_trainable, batch_size, learning_rate,
    #                         optimizer, model_name, n_epoch=50, add_features=True, scale_features=True,
    #                         overwrite=False,
    #                         use_cyclical_lr=False, eval_on_train=False, add_intra_sentence_attention=add)
    #     else:
    #         train_model(genre, input_level, word_embed_type, word_embed_trainable, batch_size, learning_rate,
    #                     optimizer, model_name, n_epoch=50, add_features=True, scale_features=True,
    #                     use_cyclical_lr=False, overwrite=False, eval_on_train=False)

    # train_model('mednli', 'word', 'glove_cc', False, 128, 0.001, 'adam', 'KerasInfersent', overwrite=False,
    #             eval_on_train=False, encoder_type='self_attentive')

    # model_names = ['KerasInfersent', 'KerasEsim', 'KerasSiameseBiLSTM', 'KerasSiameseCNN', 'KerasIACNN',
    #                'KerasDecomposable']
    # genres = ['mednli']
    # input_levels = ['word']
    # word_embed_types = ['glove_cc']
    # word_embed_trainables = [False]
    # batch_sizes = [32]
    # learning_rates = [0.001]
    # optimizer_types = ['adam']
    # input_configs = ['cache_elmo']
    # elmo_output_modes = ['elmo_avg']
    # elmo_model_types = ['bilmtf']
    #
    # for model_name, genre, input_level, word_embed_type, word_embed_trainable, batch_size, learning_rate, optimizer, \
    #     input_config, elmo_output_mode, elmo_model_type in product(model_names, genres, input_levels, word_embed_types,
    #                                                                 word_embed_trainables, batch_sizes, learning_rates,
    #                                                                optimizer_types, input_configs, elmo_output_modes,
    #                                                                elmo_model_types):
    #     if model_name == 'KerasInfersent':
    #         for encoder_type in ['lstm', 'gru', 'bilstm', 'bigru', 'bilstm_max_pool', 'bilstm_mean_pool',
    #                              'self_attentive', 'h_cnn']:
    #             train_model(genre, input_level, word_embed_type, word_embed_trainable, batch_size, learning_rate,
    #                         optimizer, model_name, overwrite=False, eval_on_train=False, input_config=input_config,
    #                         elmo_model_type=elmo_model_type, elmo_output_mode=elmo_output_mode,
    #                         encoder_type=encoder_type)
    #
    #     elif model_name == 'KerasDecomposable':
    #         for add in [True, False]:
    #             train_model(genre, input_level, word_embed_type, word_embed_trainable, batch_size, learning_rate,
    #                         optimizer, model_name, overwrite=False, eval_on_train=False, input_config=input_config,
    #                         elmo_model_type=elmo_model_type, elmo_output_mode=elmo_output_mode,
    #                         add_intra_sentence_attention=add)
    #     else:
    #         train_model(genre, input_level, word_embed_type, word_embed_trainable, batch_size, learning_rate, optimizer,
    #                     model_name, overwrite=False, eval_on_train=False, input_config=input_config,
    #                     elmo_model_type=elmo_model_type, elmo_output_mode=elmo_output_mode)

    # train_bert('mednli', 'word', 32)

    # lr range test
    # model_names = ['KerasInfersent', 'KerasEsim', 'KerasSiameseBiLSTM', 'KerasSiameseCNN', 'KerasIACNN',
    #                'KerasDecomposable']
    # genres = ['mednli']
    # input_levels = ['word']
    # word_embed_types = ['glove_cc']
    # word_embed_trainables = [False]
    # batch_sizes = [32]
    # learning_rates = [0.001]
    # optimizer_types = ['adam']
    #
    # for model_name, genre, input_level, word_embed_type, word_embed_trainable, batch_size, learning_rate, optimizer \
    #         in product(model_names, genres, input_levels, word_embed_types, word_embed_trainables, batch_sizes,
    #                    learning_rates, optimizer_types):
    #     if model_name == 'KerasInfersent':
    #         for encoder_type in ['lstm', 'gru', 'bilstm', 'bigru', 'bilstm_max_pool', 'bilstm_mean_pool',
    #                              'self_attentive', 'h_cnn']:
    #             train_model(genre, input_level, word_embed_type, word_embed_trainable, batch_size, learning_rate,
    #                         optimizer, model_name, lr_range_test=True, use_cyclical_lr=False, add_features=False,
    #                         scale_features=False, overwrite=False, eval_on_train=False, encoder_type=encoder_type)
    #     elif model_name == 'KerasDecomposable':
    #         for add in [True, False]:
    #             train_model(genre, input_level, word_embed_type, word_embed_trainable, batch_size, learning_rate,
    #                         optimizer, model_name, lr_range_test=True, use_cyclical_lr=False, add_features=False,
    #                         scale_features=False, overwrite=False, eval_on_train=False,
    #                         add_intra_sentence_attention=add)
    #     else:
    #         train_model(genre, input_level, word_embed_type, word_embed_trainable, batch_size, learning_rate,
    #                     optimizer, model_name, lr_range_test=True, use_cyclical_lr=False, add_features=False,
    #                     scale_features=False, overwrite=False, eval_on_train=False)
    # train_model('mednli', 'word', 'glove_cc', False, 32, 0.001, 'adam', 'KerasRefinedSSAModel', n_epoch=5,
    #             lr_range_test=True, use_cyclical_lr=False, add_features=False, scale_features=False,
    #             add_penalty=False)

    train_model('mednli', 'word', 'glove_cc', False, 64, 0.01, 'adam', 'KerasInfersent', n_epoch=5,
                add_features=False, scale_features=False, lr_range_test=True, encoder_type='bilstm_max_pool')
    # train_model('mednli', 'word', 'glove_cc', False, 32, 0.001, 'adam', 'KerasInfersent', n_epoch=50,
    #             lr_range_test=False, use_cyclical_lr=False, add_features=False, scale_features=False,
    #             encoder_type='bilstm_max_pool')
    # train_model('mednli', 'word', 'glove_cc', False, 32, 0.001, 'adam', 'KerasInfersent', n_epoch=50,
    #             lr_range_test=False, use_cyclical_lr=False, add_features=True, scale_features=False,
    #             encoder_type='bilstm_max_pool')
    # train_model('mednli', 'word', 'glove_cc', False, 32, 0.001, 'adam', 'KerasInfersent', n_epoch=50,
    #             lr_range_test=False, use_cyclical_lr=False, add_features=True, scale_features=True,
    #             encoder_type='bilstm_max_pool')
    # train_model('mednli', 'word', 'glove_cc', False, 32, 0.001, 'adam', 'KerasInfersent', n_epoch=16,
    #             lr_range_test=False, use_cyclical_lr=True, add_features=False, scale_features=False,
    #             encoder_type='bilstm_max_pool')
    # train_model('mednli', 'word', 'glove_cc', False, 32, 0.001, 'adam', 'KerasInfersent', n_epoch=16,
    #             lr_range_test=False, use_cyclical_lr=True, add_features=True, scale_features=False,
    #             encoder_type='bilstm_max_pool')
    # train_model('mednli', 'word', 'glove_cc', False, 32, 0.001, 'adam', 'KerasInfersent', n_epoch=16,
    #             lr_range_test=False, use_cyclical_lr=True, add_features=True, scale_features=True,
    #             encoder_type='bilstm_max_pool')
    #
    # train_model('mednli', 'word', 'glove_cc', False, 64, 0.001, 'adam', 'KerasInfersent', n_epoch=50,
    #             lr_range_test=False, use_cyclical_lr=False, add_features=False, scale_features=False,
    #             encoder_type='bilstm_max_pool')
    # train_model('mednli', 'word', 'glove_cc', False, 64, 0.001, 'adam', 'KerasInfersent', n_epoch=50,
    #             lr_range_test=False, use_cyclical_lr=False, add_features=True, scale_features=False,
    #             encoder_type='bilstm_max_pool')
    # train_model('mednli', 'word', 'glove_cc', False, 64, 0.001, 'adam', 'KerasInfersent', n_epoch=50,
    #             lr_range_test=False, use_cyclical_lr=False, add_features=True, scale_features=True,
    #             encoder_type='bilstm_max_pool')
    # train_model('mednli', 'word', 'glove_cc', False, 64, 0.001, 'adam', 'KerasInfersent', n_epoch=16,
    #             lr_range_test=False, use_cyclical_lr=True, add_features=False, scale_features=False,
    #             encoder_type='bilstm_max_pool')
    # train_model('mednli', 'word', 'glove_cc', False, 64, 0.001, 'adam', 'KerasInfersent', n_epoch=16,
    #             lr_range_test=False, use_cyclical_lr=True, add_features=True, scale_features=False,
    #             encoder_type='bilstm_max_pool')
    # train_model('mednli', 'word', 'glove_cc', False, 64, 0.001, 'adam', 'KerasInfersent', n_epoch=16,
    #             lr_range_test=False, use_cyclical_lr=True, add_features=True, scale_features=True,
    #             encoder_type='bilstm_max_pool')
    #
    # train_model('mednli', 'word', 'glove_cc', False, 32, 0.001, 'adam', 'KerasRefinedSSAModel', n_epoch=50,
    #             lr_range_test=False, use_cyclical_lr=False, add_features=False, scale_features=False)
    # train_model('mednli', 'word', 'glove_cc', False, 32, 0.001, 'adam', 'KerasRefinedSSAModel', n_epoch=50,
    #             lr_range_test=False, use_cyclical_lr=False, add_features=True, scale_features=False)
    # train_model('mednli', 'word', 'glove_cc', False, 32, 0.001, 'adam', 'KerasRefinedSSAModel', n_epoch=50,
    #             lr_range_test=False, use_cyclical_lr=False, add_features=True, scale_features=True)
    # train_model('mednli', 'word', 'glove_cc', False, 32, 0.001, 'adam', 'KerasRefinedSSAModel', n_epoch=16,
    #             lr_range_test=False, use_cyclical_lr=True, add_features=False, scale_features=False)
    # train_model('mednli', 'word', 'glove_cc', False, 32, 0.001, 'adam', 'KerasRefinedSSAModel', n_epoch=16,
    #             lr_range_test=False, use_cyclical_lr=True, add_features=True, scale_features=False)
    # train_model('mednli', 'word', 'glove_cc', False, 32, 0.001, 'adam', 'KerasRefinedSSAModel', n_epoch=16,
    #             lr_range_test=False, use_cyclical_lr=True, add_features=True, scale_features=True)
    #
    # train_model('mednli', 'word', 'glove_cc', False, 64, 0.001, 'adam', 'KerasRefinedSSAModel', n_epoch=50,
    #             lr_range_test=False, use_cyclical_lr=False, add_features=False, scale_features=False)
    # train_model('mednli', 'word', 'glove_cc', False, 64, 0.001, 'adam', 'KerasRefinedSSAModel', n_epoch=50,
    #             lr_range_test=False, use_cyclical_lr=False, add_features=True, scale_features=False)
    # train_model('mednli', 'word', 'glove_cc', False, 64, 0.001, 'adam', 'KerasRefinedSSAModel', n_epoch=50,
    #             lr_range_test=False, use_cyclical_lr=False, add_features=True, scale_features=True)
    # train_model('mednli', 'word', 'glove_cc', False, 64, 0.001, 'adam', 'KerasRefinedSSAModel', n_epoch=16,
    #             lr_range_test=False, use_cyclical_lr=True, add_features=False, scale_features=False)
    # train_model('mednli', 'word', 'glove_cc', False, 64, 0.001, 'adam', 'KerasRefinedSSAModel', n_epoch=16,
    #             lr_range_test=False, use_cyclical_lr=True, add_features=True, scale_features=False)
    # train_model('mednli', 'word', 'glove_cc', False, 64, 0.001, 'adam', 'KerasRefinedSSAModel', n_epoch=16,
    #             lr_range_test=False, use_cyclical_lr=True, add_features=True, scale_features=True)

    # train_model('mednli', 'word', 'glove_cc', False, 64, 0.001, 'adam', 'KerasInfersent', n_epoch=20,
    #             add_features=False, scale_features=False, overwrite=False, lr_range_test=False,
    #             callbacks_to_add=['modelcheckpoint', 'clr', 'swa'], encoder_type='bilstm_max_pool')
    # train_model('mednli', 'word', 'glove_cc', False, 64, 0.001, 'adam', 'KerasInfersent', n_epoch=20,
    #             add_features=False, scale_features=False, overwrite=False, lr_range_test=False,
    #             callbacks_to_add=['modelcheckpoint', 'sgdr', 'swa'], encoder_type='bilstm_max_pool')
    # train_model('mednli', 'word', 'glove_cc', False, 64, 0.001, 'adam', 'KerasInfersent', n_epoch=20,
    #             add_features=False, scale_features=False, overwrite=False, lr_range_test=False,
    #             callbacks_to_add=['modelcheckpoint', 'sse'], encoder_type='bilstm_max_pool')
    # train_model('mednli', 'word', 'glove_cc', False, 64, 0.001, 'adam', 'KerasInfersent', n_epoch=20,
    #             add_features=False, scale_features=False, overwrite=False, lr_range_test=False,
    #             callbacks_to_add=['modelcheckpoint', 'fge'], encoder_type='bilstm_max_pool')
    # train_model('mednli', 'word', 'glove_cc', False, 64, 0.001, 'adam', 'KerasInfersent', n_epoch=20,
    #             add_features=False, scale_features=False, overwrite=False, lr_range_test=False,
    #             callbacks_to_add=['modelcheckpoint', 'swa_clr'], encoder_type='bilstm_max_pool')
    # train_model('mednli', 'word', 'glove_cc', False, 64, 0.001, 'adam', 'KerasInfersent', n_epoch=20,
    #             add_features=False, scale_features=False, overwrite=False, lr_range_test=False,
    #             callbacks_to_add=['modelcheckpoint', 'clr_1', 'swa'], encoder_type='bilstm_max_pool')
    # train_model('mednli', 'word', 'glove_cc', False, 64, 0.001, 'adam', 'KerasInfersent', n_epoch=20,
    #             add_features=False, scale_features=False, overwrite=False, lr_range_test=False,
    #             callbacks_to_add=['modelcheckpoint', 'clr_2', 'swa'], encoder_type='bilstm_max_pool')

    # train_model('mednli', 'word', 'glove_cc', False, 64, 0.001, 'adam', 'KerasEsim', n_epoch=20,
    #             add_features=False, scale_features=False, overwrite=False, lr_range_test=False,
    #             callbacks_to_add=['modelcheckpoint', 'clr', 'swa'])
    # train_model('mednli', 'word', 'glove_cc', False, 64, 0.001, 'adam', 'KerasEsim', n_epoch=20,
    #             add_features=False, scale_features=False, overwrite=False, lr_range_test=False,
    #             callbacks_to_add=['modelcheckpoint', 'sgdr', 'swa'])
    # train_model('mednli', 'word', 'glove_cc', False, 64, 0.001, 'adam', 'KerasEsim', n_epoch=20,
    #             add_features=False, scale_features=False, overwrite=False, lr_range_test=False,
    #             callbacks_to_add=['modelcheckpoint', 'sse'])
    # train_model('mednli', 'word', 'glove_cc', False, 64, 0.001, 'adam', 'KerasEsim', n_epoch=20,
    #             add_features=False, scale_features=False, overwrite=False, lr_range_test=False,
    #             callbacks_to_add=['modelcheckpoint', 'fge'])
    # train_model('mednli', 'word', 'glove_cc', False, 64, 0.001, 'adam', 'KerasEsim', n_epoch=20,
    #             add_features=False, scale_features=False, overwrite=False, lr_range_test=False,
    #             callbacks_to_add=['modelcheckpoint', 'swa_clr'])
    # train_model('mednli', 'word', 'glove_cc', False, 64, 0.001, 'adam', 'KerasEsim', n_epoch=20,
    #             add_features=False, scale_features=False, overwrite=False, lr_range_test=False,
    #             callbacks_to_add=['modelcheckpoint', 'clr_1', 'swa'])
    # train_model('mednli', 'word', 'glove_cc', False, 64, 0.001, 'adam', 'KerasEsim', n_epoch=20,
    #             add_features=False, scale_features=False, overwrite=False, lr_range_test=False,
    #             callbacks_to_add=['modelcheckpoint', 'clr_2', 'swa'])

    # train_model('mednli', 'word', 'glove_cc', False, 32, 0.001, 'adam', 'KerasInfersent', n_epoch=20,
    #             add_features=False, scale_features=False, overwrite=False, lr_range_test=False,
    #             callbacks_to_add=['modelcheckpoint', 'clr', 'swa'], encoder_type='bilstm_max_pool')
    # train_model('mednli', 'word', 'glove_cc', False, 32, 0.001, 'adam', 'KerasInfersent', n_epoch=20,
    #             add_features=False, scale_features=False, overwrite=False, lr_range_test=False,
    #             callbacks_to_add=['modelcheckpoint', 'sgdr', 'swa'], encoder_type='bilstm_max_pool')
    # train_model('mednli', 'word', 'glove_cc', False, 32, 0.001, 'adam', 'KerasInfersent', n_epoch=20,
    #             add_features=False, scale_features=False, overwrite=False, lr_range_test=False,
    #             callbacks_to_add=['modelcheckpoint', 'sse'], encoder_type='bilstm_max_pool')
    # train_model('mednli', 'word', 'glove_cc', False, 32, 0.001, 'adam', 'KerasInfersent', n_epoch=20,
    #             add_features=False, scale_features=False, overwrite=False, lr_range_test=False,
    #             callbacks_to_add=['modelcheckpoint', 'fge'], encoder_type='bilstm_max_pool')
    # train_model('mednli', 'word', 'glove_cc', False, 32, 0.001, 'adam', 'KerasInfersent', n_epoch=20,
    #             add_features=False, scale_features=False, overwrite=False, lr_range_test=False,
    #             callbacks_to_add=['modelcheckpoint', 'swa_clr'], encoder_type='bilstm_max_pool')
    # train_model('mednli', 'word', 'glove_cc', False, 32, 0.001, 'adam', 'KerasInfersent', n_epoch=20,
    #             add_features=False, scale_features=False, overwrite=False, lr_range_test=False,
    #             callbacks_to_add=['modelcheckpoint', 'clr_1', 'swa'], encoder_type='bilstm_max_pool')
    # train_model('mednli', 'word', 'glove_cc', False, 32, 0.001, 'adam', 'KerasInfersent', n_epoch=20,
    #             add_features=False, scale_features=False, overwrite=False, lr_range_test=False,
    #             callbacks_to_add=['modelcheckpoint', 'clr_2', 'swa'], encoder_type='bilstm_max_pool')

    # train_model('mednli', 'word', 'glove_cc', False, 32, 0.001, 'adam', 'KerasEsim', n_epoch=20,
    #             add_features=False, scale_features=False, overwrite=False, lr_range_test=False,
    #             callbacks_to_add=['modelcheckpoint', 'clr', 'swa'])
    # train_model('mednli', 'word', 'glove_cc', False, 32, 0.001, 'adam', 'KerasEsim', n_epoch=20,
    #             add_features=False, scale_features=False, overwrite=False, lr_range_test=False,
    #             callbacks_to_add=['modelcheckpoint', 'sgdr', 'swa'])
    # train_model('mednli', 'word', 'glove_cc', False, 32, 0.001, 'adam', 'KerasEsim', n_epoch=20,
    #             add_features=False, scale_features=False, overwrite=False, lr_range_test=False,
    #             callbacks_to_add=['modelcheckpoint', 'sse'])
    # train_model('mednli', 'word', 'glove_cc', False, 32, 0.001, 'adam', 'KerasEsim', n_epoch=20,
    #             add_features=False, scale_features=False, overwrite=False, lr_range_test=False,
    #             callbacks_to_add=['modelcheckpoint', 'fge'])
    # train_model('mednli', 'word', 'glove_cc', False, 32, 0.001, 'adam', 'KerasEsim', n_epoch=20,
    #             add_features=False, scale_features=False, overwrite=False, lr_range_test=False,
    #             callbacks_to_add=['modelcheckpoint', 'swa_clr'])
    # train_model('mednli', 'word', 'glove_cc', False, 32, 0.001, 'adam', 'KerasEsim', n_epoch=20,
    #             add_features=False, scale_features=False, overwrite=False, lr_range_test=False,
    #             callbacks_to_add=['modelcheckpoint', 'clr_1', 'swa'])
    # train_model('mednli', 'word', 'glove_cc', False, 32, 0.001, 'adam', 'KerasEsim', n_epoch=20,
    #             add_features=False, scale_features=False, overwrite=False, lr_range_test=False,
    #             callbacks_to_add=['modelcheckpoint', 'clr_2', 'swa'])





"""Grid Search (especially for neural models)."""
import csv
import logging
import os
from datetime import datetime
from typing import List

import numpy as np
from fire import Fire
from numpy.random import choice, randint, uniform

from data_utility import load_data
from run_stance_detection import run_fixed_fast, run_train, run_xval
from sklearn.model_selection import ParameterGrid

logger = logging.getLogger(__name__)


def get_param_grid(modelname):
    """Generate parameter grid.

    Directly edit the candidate parameters here.
    Recommend to make `git commit` before running the script in order to record what you did.
    """
    param_combs = dict(
        max_vocabsize=[100_000, 200_000, 300_000],
        max_seqlen=[20, 40],
        # max_tgtlen=[1, 4],
        max_tgtlen=[1],  # for SLO, we just need 1 token
        profile=[False, True],
        max_prflen=[20, 40],
        dropout=[0.1, 0.3, 0.6, 0.9],  # an advice from Shaukat
        lr=[0.1, 0.01, 0.001, 0.0001],
        validation_split=[0.2],
        epochs=[200],  # note that early_stopping is applied
        batch_size=[32, 64, 128, 256],
        patience=[30]  # early stopping
    )
    if modelname in ['crossnet', 'cn', 'CrossNet', 'crossNet']:
        param_combs['dim_lstm'] = [100, 200, 300]
        param_combs['num_reason'] = [1, 2, 3]
        param_combs['dim_dense'] = [100, 200, 300]
    elif modelname in ['memnet', 'MemNet', 'mn', 'memNet', 'AttNet', 'attnet']:
        param_combs['dim_lstm'] = [100, 200, 300]
        param_combs['num_layers'] = [1, 2, 3, 4]
    elif modelname in ['tf', 'transformer', 'Transformer']:
        param_combs['target'] = [False, True]
        # param_combs['dim_pff'] = [64, 128, 256, 512]
        param_combs['num_head'] = [2, 4, 8]
        param_combs['num_layers'] = [1, 2, 3, 4]
    else:
        raise NotImplementedError

    return list(ParameterGrid(param_combs))


def filter_useless_combs(params):
    """if you find any useless parameter combinations automatically generated by ParameterGrid, you can skip that by adding rules here."""
    return False


def randsample_params(modelname):
    """Randomly sample parameters on every call.

    Directly edit the candidate parameter ranges here.
    Recommend to make `git commit` before running the script in order to record what you did.
    """
    param_combs = dict(
        # max_vocabsize=100_000 * randint(1, 4),
        max_vocabsize=10000,
        max_seqlen=choice([20, 40]),
        # max_tgtlen=[1, 4],
        max_tgtlen=1,  # for SLO, we just need 1 token
        profile=choice([False, True]),
        prf_cat=choice([False, True]),
        max_prflen=choice([20, 40]),
        dropout=uniform(0.1, 0.5),  # an advice from Shaukat
        lr=10 ** uniform(-5, -1),
        validation_split=0.2,
        epochs=200,  # note that early_stopping is applied
        batch_size=2 ** randint(5, 9),
        patience=30  # early stopping
    )
    if modelname in ['crossnet', 'cn', 'CrossNet', 'crossNet']:
        param_combs['dim_lstm'] = 100 * randint(1, 6)
        # param_combs['num_reason'] = randint(1, 4)
        param_combs['num_reason'] = 1
        param_combs['dim_dense'] = 100 * randint(1, 6)
    elif modelname in ['memnet', 'MemNet', 'mn', 'memNet', 'AttNet', 'attnet']:
        param_combs['dim_lstm'] = 100 * randint(1, 6)
        param_combs['num_layers'] = randint(1, 5)
        param_combs['weight_tying'] = choice([False, True])
    elif modelname in ['tf', 'transformer', 'Transformer']:
        # param_combs['m_profile'] = choice([1, 2])
        # param_combs['target'] = choice([False, 1, 2])
        param_combs['target'] = 1
        # param_combs['parallel'] = choice([False, 1, 2, 3])
        param_combs['parallel'] = 1
        # param_combs['dim_pff'] = choice([64, 128, 256, 512])  # dynamic
        param_combs['num_head'] = 2 ** randint(1, 4)
        param_combs['num_layers'] = randint(1, 5)
    else:
        raise NotImplementedError

    return param_combs


class GridSearch():
    """The main interface to conduct grid search.

    if `trainfp` is not None, search is conducted on the fixed train/test split.
    else, 3-fold cross validation on `datafp` is executed.
    """

    def __init__(self, model, wvfp,
                 rand=None,
                 repeat=3, cv=3,
                 path='.',
                 logging_level=logging.DEBUG,
                 logging_filename=None
                 ):
        """Initialize stance detection system.

        Keyword Arguments
        :param model: the name of the learning model to use (svm, crossnet, ...)
        :param wvfp: the system filepath of the word embedding vectors
        :param rand: the number of sampling of hyper parameters. if any integer specified, randomised search is applied. (default: None)
        :param repeat: the number of times to run the classifier per each parameter combination. only used for 'fixed' mode
                (default: 3)
        :param cv: the number of cross validation split, only for 'xval'
                (default=3)
        :param path: the root path for all filepaths
            (default: '.')
        :param logging_level: the level of logging to use (DEBUG - 10; INFO - 20; ...)
            (default: logging.DEBUG)
        :param logging_filename: the file in which to save logging output, if any
            (default: grid_search-MODEL-DATE.log)
        """
        if model == 'svm':
            raise ValueError(
                'This script is currently incompatible with SVM. FYI, SVM is always tuned when they fit to data. (see models.svm_mohammad17)')
        self.model = model
        self.path = path
        self.wvfp = os.path.join(self.path, wvfp) if wvfp else None
        self.rand = rand
        self.repeat = repeat
        self.cv = cv

        # logger setup
        self.startdate = datetime.now()
        sn = 'random' if self.rand else 'grid'
        self.basename = f'{sn}_search-{self.model}-{self.startdate:%d%b%Y}'
        logging.basicConfig(
            level=logging_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            filename=logging_filename if logging_filename else self.basename + '.log',
        )
        # simultaenuously output INFO logs to stderr
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        logging.getLogger(__name__).addHandler(console)

        # TODO: need wordvec routine
        # pass a folder path containing wordvecs
        # load once for each wv file and pass those objects (KeyedVectors) as parameters
        if self.rand:
            self.param_grid = [randsample_params(model)
                               for _ in range(rand)]
        else:
            self.param_grid = get_param_grid(model)

        # csv writer setup
        self._csvf = open(self.basename + '.csv', 'w')
        header = list(self.param_grid[0].keys())
        header += [f'fmacro_{i+1}' for i in range(self.repeat)]
        header += ['fmacro_avg', 'fmacro_std']
        self.writer = csv.DictWriter(self._csvf, fieldnames=header)
        self.writer.writeheader()

    def fixed(self, trainfp, testfp):
        """Run a standard train/test cycle on the given data.

        Keyword Arguments
        :param trainfp: the system filepath of the CSV training dataset
        :param testfp: the system filepath of the CSV testing dataset
        """
        logger.info(
            f'Exhaustive GRID SEARCH on the model "{self.model}" '
            f'for {len(self.param_grid)} parameter combinations '
            f'with {self.repeat} repetition')

        trainfp = os.path.join(self.path, trainfp)
        testfp = os.path.join(self.path, testfp)
        x_train_arys, y_train_arys = \
            load_data(trainfp, target='all', profile=False)
        x_train_arys_p, y_train_arys_p = \
            load_data(trainfp, target='all', profile=True)
        x_test_arys, y_test_arys = \
            load_data(testfp, target='all', profile=False)
        x_test_arys_p, y_test_arys_p = \
            load_data(testfp, target='all', profile=True)
        for params in self.param_grid:
            # TODO: error tolerance
            if filter_useless_combs(params):
                continue
            logger.info(str(params))
            profile = params.pop('profile', None)
            fmacro_list: List[float] = []
            for i in range(self.repeat):
                if self.repeat > 1:
                    logger.info(f'iteration: {i+1}')
                if profile:
                    fmacro = run_fixed_fast(self.model,
                                            x_train_arys_p, y_train_arys_p,
                                            x_test_arys_p, y_test_arys_p,
                                            self.wvfp, profile,
                                            params=params)
                else:
                    fmacro = run_fixed_fast(self.model,
                                            x_train_arys, y_train_arys,
                                            x_test_arys, y_test_arys,
                                            self.wvfp, profile,
                                            params=params)
                fmacro_list.append(fmacro)
            self._result2csvrow(params, fmacro_list)
        self._csvf.close()

    def xval(self, datafp):
        """Run a cross-validation test on the given data.

        Keyword Arguments
        :param datafp: the system filepath of the CSV dataset
        """
        if self.rand:
            searchname = f'RANDOM SEARCH on the model "{self.model}" '
        else:
            searchname = f'Exhaustive GRID SEARCH on the model "{self.model}" '
        logger.info(
            searchname +
            f'for {len(self.param_grid)} parameter combinations '
            f'with {self.repeat} repetition')
        datafp = os.path.join(self.path, datafp)
        x_arys, y_arys = load_data(
            datafp, target='all', profile=False)
        x_arys_p, y_arys_p = load_data(
            datafp, target='all', profile=True)
        for params in self.param_grid:
            if filter_useless_combs(params):
                continue
            logger.info(str(params))
            profile = params.pop('profile', None)
            if profile:
                fmacro_list = run_xval(self.model, x_arys_p, y_arys_p,
                                       self.wvfp, profile,
                                       cv=self.cv, params=params)
            else:
                fmacro_list = run_xval(self.model, x_arys, y_arys,
                                       self.wvfp, profile,
                                       cv=self.cv, params=params)
            self._result2csvrow(params, fmacro_list)
        self._csvf.close()

    def _result2csvrow(self, params, fmacro_list):
        average = np.average(fmacro_list)
        stdev = np.std(fmacro_list)

        logger.info(f'total iterations: {self.repeat}; '
                    f'fmacro average: {average:.4}; '
                    f'fmacro std dev: {stdev:.4}')

        row = {f'fmacro_{i+1}': v for i, v in enumerate(fmacro_list)}
        row.update({'fmacro_avg': average, 'fmacro_std': stdev})
        row.update(params)
        self.writer.writerow(row)


if __name__ == '__main__':
    Fire(GridSearch)

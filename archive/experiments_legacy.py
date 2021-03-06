__author__ = 'fiona.collins'

import torch
from sklearn.model_selection import ParameterGrid
from torch_geometric.data import DataLoader
import torch_geometric.transforms as T

from datasets.bim import BIM
from datasets.ModelNet import ModelNet
from datasets.splits import random_splits

from learning.models import PN2Net, DGCNNNet, UNet, PointNet
from learning.trainers import Trainer

import os
import pandas as pd
import matplotlib
matplotlib.use("pgf")
matplotlib.rcParams.update({
    "pgf.texsystem": "pdflatex",
    'font.family': 'serif',
    'text.usetex': True,
    'pgf.rcfonts': False,
})
plt = matplotlib.pyplot
from sklearn.manifold import TSNE
from sklearn.metrics import confusion_matrix, classification_report
from pandas import DataFrame

import numpy as np
from helpers.set_plot import Set_analyst
from torch.utils.data import WeightedRandomSampler

# Define depending on hardware
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
# device = 'cpu'


class Experimenter(object):
    def __init__(self, config):
        self.grid = ParameterGrid(config)

    def run(self):
        # path = '../data/Dummy'
        cdw = cwd = os.getcwd()

        """
        transform = T.Compose([T.Distance(), T.Center()])
        #,
        path = '../../BIM_PC/points'
        dataset = BIM(path, True, transform)
        test_data = BIM(path, False, transform)
        """

        path = '../../BIM_PC_T1'
        transform = T.Compose([T.NormalizeScale(), T.Center(), T.SamplePoints(1024)])
        dataset = BIM(path, 'T1', True, transform)
        #dataset = dataset[:15].copy_set()
        test_data = BIM(path, 'T1', False, transform)
        #test_data = test_data[:15].copy_set()

        _, train_index, val_index = random_splits(dataset, dataset.num_classes)

        train_dataset = dataset[dataset.train_mask].copy_set(train_index)
        val_dataset = dataset[dataset.val_mask].copy_set(val_index)

        print("Training {} graphs with {} number of classes" .format(len(train_dataset), train_dataset.num_classes))
        print("Validating on {} graphs with {} number of classes: ". format(len(val_dataset), val_dataset.num_classes))

        l_per_class = Set_analyst(given_set=train_dataset).class_counter()

        weights_dict = [(tup[0], 1 / tup[1]) for tup in list(l_per_class.items())]
        weights = [1 / tup[1] for tup in list(l_per_class.items())]
        samples_weights = [weights[t] for t in train_dataset.data.y]
        samples_weights = torch.from_numpy(np.array(samples_weights)).double()
        sampler = WeightedRandomSampler(samples_weights, len(samples_weights))

        results = []
        grid_unfold = list(self.grid)

        for i, params in enumerate(grid_unfold):
            print("Run {} of {}".format(i, len(grid_unfold)))
            output_path = '../out/' + str(i)

            if not os.path.exists(output_path):
                os.makedirs(output_path)

            result = params

            n_epochs = params['n_epochs']
            batch_size = params['batch_size']
            learning_rate = params['learning_rate']
            model_name = params['model_name']

            Set_analyst(given_set=train_dataset).bar_plot("train_set")
            train_loader = DataLoader(train_dataset, batch_size=batch_size, num_workers=0, sampler=sampler)
            val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False, num_workers=0)
            test_loader = DataLoader(test_data, batch_size=batch_size, shuffle=False, num_workers=0)
            Set_analyst(train_loader).bar_plot("train")
            Set_analyst(val_loader).bar_plot("val")
            Set_analyst(test_loader).bar_plot("test")

            if model_name.__name__ is 'PN2Net':
                model = model_name(out_channels=train_dataset.num_classes).to(device)
            if model_name.__name__ is 'PointNet':
                model = model_name(classes=train_dataset.num_classes).to(device)
            if model_name.__name__ is 'DGCNNNet':
                model = model_name(out_channels=train_dataset.num_classes).to(device)

            if model_name.__name__ is 'UNet':
                # TODO : make a bit nicer...
                """transform = T.Compose([T.KNNGraph(k=3), T.Distance(), T.Center()])
                dataset = BIM(path, True, transform)
                test_data = BIM(path, False, transform)
                train_data = dataset[:train_size]"""
                path_trick= path+'_points'
                transform, pretransform = T.Compose([T.NormalizeScale(), T.KNNGraph(k=3)]) , T.SamplePoints(1024)
                dataset = ModelNet(path_trick, '10', True, transform, pretransform)
                test_data = ModelNet(path_trick, '10', False, transform, pretransform)

                _, train_index, val_index = random_splits(dataset, dataset.num_classes)

                train_dataset = dataset[dataset.train_mask]  # .copy_set(train_index)
                val_dataset = dataset[dataset.val_mask]  # .copy_set(val_index)

                l_per_class = Set_analyst(given_set=train_dataset).class_counter()

                weights_dict = [(tup[0], 1 / tup[1]) for tup in list(l_per_class.items())]
                weights = [1 / tup[1] for tup in list(l_per_class.items())]
                samples_weights = [weights[t] for t in train_dataset.data.y]
                samples_weights = torch.from_numpy(np.array(samples_weights)).double()
                sampler = WeightedRandomSampler(samples_weights, len(samples_weights))

                train_loader = DataLoader(train_dataset, batch_size=batch_size, num_workers=0, sampler=sampler)
                val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False, num_workers=0)
                test_loader = DataLoader(test_data, batch_size=batch_size, shuffle=False, num_workers=0)

                model = model_name(num_features=dataset.num_features, num_classes=dataset.num_classes,
                                   num_nodes=dataset.data.num_nodes).to(device)
            # num_features, num_classes, num_nodes, edge_index

            optimizer = torch.optim.Adam(params=model.parameters(), lr=learning_rate, weight_decay=0.00001)

            trainer = Trainer(model, output_path)
            epoch_losses, train_accuracies, val_accuracies = trainer.train(train_loader, val_loader, n_epochs,
                                                                           optimizer)

            test_acc, y_pred, y_real, _, _ = trainer.test(test_loader)
            result['test_acc'] = test_acc

            conf_mat = confusion_matrix(y_true=y_real, y_pred=y_pred)
            df1 = DataFrame(conf_mat)
            filename = output_path + '/confmat_report.csv'
            df1.to_csv(filename)

            target_names = test_data.classmap.values()
            real_target_names = [test_data.classmap[i] for i in np.unique(np.array(dataset.data.y))]
            class_rep = classification_report(y_true=y_real, y_pred=y_pred, target_names=real_target_names,
                                              output_dict=True)
            df2 = DataFrame(class_rep).transpose()
            filename = output_path + '/class_report.csv'
            df2.to_csv(filename)

            print('test acc = {}'.format(test_acc))

            plt.figure()
            plt.plot(range(len(epoch_losses)), epoch_losses, label='training loss')
            plt.legend()
            plt.savefig(output_path + '/training.png')
            plt.close()

            a = plt
            a.figure()
            a.plot(range(len(train_accuracies)), train_accuracies, label='training accuracies')
            a.plot(range(len(train_accuracies)), val_accuracies, label='validation accuracies')
            a.legend()
            a.savefig(output_path + '/training_acc.png')
            a.close()

            results.append(result)

            # self.plot_latent_space(model, train_loader)

            """sampler = Sampler(model)
            num_nodes = 10
            num_graphs = 2
            score = sampler.sample(num_nodes, num_graphs, threshold, enc_output_dim, dataset.id2type, dataset.id2rel, output_path)
            result['score'] = score"""
        # TODO: add final trainings loss, validato?
        pd.DataFrame(results).to_csv('../out/results.csv')
        torch.cuda.empty_cache()


if __name__ == '__main__':
    torch.cuda.empty_cache()
    config = dict()

    config['n_epochs'] = [150]
    config['learning_rate'] = [0.001]
    config['batch_size'] = [15]
    config['model_name'] = [DGCNNNet]
    # config['model_name'] = [, PN2Net, DGCNNNet, , DGCNNNet, UNet]
    ex = Experimenter(config)
    ex.run()

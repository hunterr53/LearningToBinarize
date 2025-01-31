import os
import sys
import shutil
import numpy as np
import numpy
import time, datetime
import torch
import random
import logging
import argparse
import torch.nn as nn
import torch.utils
import torch.backends.cudnn as cudnn
import torch.distributed as dist
import torch.utils.data.distributed
import torchvision
import onnx

#sys.path.append("../")
from utils import *
import utils_loss
from torchvision import datasets, transforms
from torch.autograd import Variable

# from birealnet import birealnet18
from Models import birealnetimagenet
from Models import birealnetMnist


parser = argparse.ArgumentParser("birealnet")
parser.add_argument('--batch_size', type=int, default=64, help='batch size')
parser.add_argument('--epochs', type=int, default=120, help='num of training epochs')
parser.add_argument('--learning_rate', type=float, default=0.1, help='init learning rate')
parser.add_argument('--momentum', type=float, default=0.9, help='momentum')
parser.add_argument('--weight_decay', type=float, default=0, help='weight decay')
parser.add_argument('--save', type=str, default='./Results', help='path for saving trained models')
parser.add_argument('--data', default="DataSets", metavar='DIR', help='path to dataset')
parser.add_argument('--label_smooth', type=float, default=0.1, help='label smoothing')
parser.add_argument('-j', '--workers', default=4, type=int, metavar='N',
                    help='number of data loading workers (default: 4)')
parser.add_argument('--print_interval', type=int, default=10, help='number of times to print')
args, unknown = parser.parse_known_args()

CLASSES = 10

# use_meta = 'MuitFC'
use_meta = 'Conv'
# use_meta = 'NoMeta'

if not os.path.exists('log'):
    os.mkdir('log')

fd = os.open('log/debug.txt', os.O_RDWR|os.O_CREAT)

# log_format = '%(asctime)s %(message)s'
log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
logging.basicConfig(filename='log/log.txt', filemode='a', 
                    level=logging.INFO, format=log_format, datefmt='%m/%d %I:%M:%S %p')

def train(epoch, train_loader, model, model_teacher, criterion, optimizer, scheduler, meta_optim=None, meta_scheduler=None, criterion_meta=None ):
    batch_time = AverageMeter('Time', ':6.3f')
    data_time = AverageMeter('Data', ':6.3f')
    losses = AverageMeter('Loss', ':.4e')
    top1 = AverageMeter('Acc@1', ':6.2f')
    top5 = AverageMeter('Acc@5', ':6.2f')

    progress = ProgressMeter(
        len(train_loader),
        [batch_time, data_time, losses, top1, top5],
        prefix="Epoch: [{}]".format(epoch))

    model.train()
    model_teacher.eval()
    end = time.time()
    scheduler.step()
    if use_meta != 'NoMeta':
        meta_scheduler.step()

    for param_group in optimizer.param_groups:
        cur_lr = param_group['lr']
    if use_meta != 'NoMeta':
        for param_group in meta_optim.param_groups:
            metacur_lr = param_group['lr']
        print('epoch: %d meta learning_rate: %f' % (epoch, metacur_lr )) # originally %e
    print('epoch: %d base learning_rate: %f' % (epoch, cur_lr)) # originally %e

    for i, (images, target) in enumerate(train_loader):
        data_time.update(time.time() - end)
        # images = images.cuda()
        # target = target.cuda()

        # compute output y
        logits = model(images)

        logits_teacher = model_teacher(images).detach()
        loss, _ = criterion(logits, logits_teacher, target)

        # measure accuracy and record loss
        prec1, prec5 = accuracy(logits, target, topk=(1, 5))
        n = images.size(0)
        losses.update(loss.item(), n)   #accumulated loss
        top1.update(prec1.item(), n)
        top5.update(prec5.item(), n)

        # compute gradient and do SGD step
        optimizer.zero_grad()
        if use_meta != 'NoMeta':
            meta_optim.zero_grad()
        loss.backward()
        optimizer.step()
        if use_meta != 'NoMeta':
            meta_optim.step()

        # measure elapsed time
        batch_time.update(time.time() - end)
        end = time.time()

        if i % args.print_interval == 0:
            progress.display(i)


    return losses.avg, top1.avg, top5.avg


def validate(epoch, val_loader, model, criterion, args, criterion_meta):
    batch_time = AverageMeter('Time', ':6.3f')
    losses = AverageMeter('Loss', ':.4e')
    top1 = AverageMeter('Acc@1', ':6.2f')
    top5 = AverageMeter('Acc@5', ':6.2f')
    progress = ProgressMeter(
        len(val_loader),
        [batch_time, losses, top1, top5],
        prefix='Test: ')

    # switch to evaluation mode
    model.eval()
    with torch.no_grad():
        end = time.time()
        for i, (images, target) in enumerate(val_loader):
            # images = images.cuda()
            # target = target.cuda()

            # compute output
            logits = model(images)
            loss = criterion(logits, target)
            # lossB = criterion_meta(lossB)
            # loss = loss + 0.05 * lossB

            # measure accuracy and record loss
            pred1, pred5 = accuracy(logits, target, topk=(1, 5))
            n = images.size(0)
            losses.update(loss.item(), n)
            top1.update(pred1[0], n)
            top5.update(pred5[0], n)

            # measure elapsed time
            batch_time.update(time.time() - end)
            end = time.time()

            if i % args.print_interval == 0:
                progress.display(i)

        print(' * acc@1 {top1.avg:.3f} acc@5 {top5.avg:.3f}'
              .format(top1=top1, top5=top5))

    return losses.avg, top1.avg, top5.avg

if __name__ == '__main__':
    if not torch.cuda.is_available():
        print('no gpu device available')
        # sys.exit(1)
    start_t = time.time()

    # cudnn.benchmark = True #CUDA
    # cudnn.enabled=True
    logging.info("args = %s", args)

    # load model
    model = birealnetMnist.mnistLearningNet()
    logging.info(model)
    
    torch.save(model, 'testArch.pth')
    # model_scripted = torch.jit.script(model) # Export to TorchScript
    # model_scripted.save('model_scripted.pt') # Save
    # torch.onnx.export(model, "testArch.onnx", verbose=False, export_params=True)

    # model = nn.DataParallel(model).cuda()

    # teacher model
    # model_teacher = torchvision.models.resnet18(pretrained=False)
    model_teacher = torchvision.models.resnet18(weights=False)
    # model_teacher.load_state_dict(torch.load('./resnet18.pth'))
    model_teacher.load_state_dict(torch.load('./resnet18.pth', weights_only=False, map_location='cpu'))
    logging.info(model_teacher)
    # model_teacher = nn.DataParallel(model_teacher).cuda()
    model_teacher.eval()
    # meta_met 
    meta_net_param = []
    for pname, p in model.named_parameters():
        # print(pname)
        if pname.find('meta_net') >= 0:
            meta_net_param.append(p)
    meta_net_param_id = list(map(id, meta_net_param))

    meta_optimizer = torch.optim.Adam([{'params': meta_net_param}], lr=0.001, weight_decay=0)
    meta_scheduler = torch.optim.lr_scheduler.MultiStepLR(meta_optimizer, [70, 90, 100, 110], gamma=0.1)

    criterion = nn.CrossEntropyLoss()
    # criterion = criterion.cuda()
    criterion_smooth = CrossEntropyLabelSmooth(CLASSES, args.label_smooth)
    # criterion_smooth = criterion_smooth.cuda()

    # criterion_kd = utils_loss.DistillationLoss().cuda()
    criterion_kd = utils_loss.DistillationLoss() # added

    # criterion_meta = Metaloss().cuda()
    criterion_meta = Metaloss() # added

    all_parameters = model.parameters()
    weight_parameters = []
    for pname, p in model.named_parameters():
        if p.ndimension() == 4 or pname=='classifier.0.weight' or pname == 'classifier.0.bias':
            weight_parameters.append(p)
    weight_parameters_id = list(map(id, weight_parameters))
    other_parameters = list(filter(lambda p: id(p) not in weight_parameters_id, all_parameters))

    other_parameters = list(filter(lambda p: id(p) not in meta_net_param_id, other_parameters))  #



    optimizer = torch.optim.SGD(
        [{'params': other_parameters},
         {'params': weight_parameters, 'weight_decay': args.weight_decay}],
        lr=args.learning_rate, momentum=args.momentum)


    # scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lambda step : (1.0-step/args.epochs), last_epoch=-1)
    scheduler = torch.optim.lr_scheduler.MultiStepLR(optimizer, [70, 90, 100, 110], gamma=0.1)
    start_epoch = 0
    best_top1_acc= 0

    checkpoint_tar = os.path.join(args.save, 'checkpoint.pth.tar')
    if os.path.exists(checkpoint_tar):
        logging.info('loading checkpoint {} ..........'.format(checkpoint_tar))
        checkpoint = torch.load(checkpoint_tar)
        start_epoch = checkpoint['epoch']
        best_top1_acc = checkpoint['best_top1_acc']
        model.load_state_dict(checkpoint['state_dict'], strict=False)
        logging.info("loaded checkpoint {} epoch = {}" .format(checkpoint_tar, checkpoint['epoch']))

    # adjust the learning rate according to the checkpoint
    for epoch in range(start_epoch):
        scheduler.step()

    # load training data
    traindir = os.path.join(args.data, 'train')
    valdir = os.path.join(args.data, 'val')
    normalize = transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                     std=[0.229, 0.224, 0.225])

    # data augmentation
    crop_scale = 0.08
    lighting_param = 0.1
    train_transforms = transforms.Compose([
        # transforms.RandomResizedCrop(224, scale=(crop_scale, 1.0)),
        Lighting(lighting_param),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        normalize])

    # train_dataset = torchvision.datasets.ImageFolder(
    #     traindir,
    #     transform=train_transforms)
    train_dataset = torchvision.datasets.MNIST(
        root= args.data,
        train=True,
        download=True,
        transform=transforms.ToTensor()
    )

    train_loader = torch.utils.data.DataLoader(
        train_dataset, batch_size=args.batch_size, shuffle=True,
        num_workers=args.workers, pin_memory=True)

    # load validation data    
    val_dataset = torchvision.datasets.MNIST(
        root= args.data,
        train=False,
        download=True,
        transform=transforms.ToTensor()
    )

    val_loader = torch.utils.data.DataLoader(
        val_dataset, batch_size=args.batch_size, shuffle=False,
        num_workers=args.workers, pin_memory=True)

    # train the model
    epoch = start_epoch
    while epoch < args.epochs:
        train_obj, train_top1_acc,  train_top5_acc = train(epoch,  train_loader, model, model_teacher, criterion_kd, optimizer, scheduler,
                                                           meta_optimizer, meta_scheduler, criterion_meta)
        valid_obj, valid_top1_acc, valid_top5_acc = validate(epoch, val_loader, model, criterion, args, criterion_meta)

        is_best = False
        if valid_top1_acc > best_top1_acc:
            best_top1_acc = valid_top1_acc
            is_best = True

        save_checkpoint({
            'epoch': epoch,
            'state_dict': model.state_dict(),
            'best_top1_acc': best_top1_acc,
            'optimizer' : optimizer.state_dict(),
            }, is_best, args.save)

        epoch += 1

    training_time = (time.time() - start_t) / 3600
    print('total training time = {} hours. best acc: {}'.format(training_time, best_top1_acc))

    
    os.close(fd)


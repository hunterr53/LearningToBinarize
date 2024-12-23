clear
# python3 trainimagenet.py --data DataSets/imagenet-1k | tee -a log/log.txt
echo 'Running training script'
python trainMnist.py --data DataSets/MNIST | tee -a log/log.txt

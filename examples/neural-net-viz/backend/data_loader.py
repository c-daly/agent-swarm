import numpy as np
import os

def download_mnist():
    """Download MNIST using tensorflow.keras.datasets"""
    try:
        from tensorflow.keras.datasets import mnist
        (X_train, y_train), (X_test, y_test) = mnist.load_data()
        return (X_train, y_train), (X_test, y_test)
    except Exception as e:
        print(f"Error downloading MNIST: {e}")
        raise

def load_mnist():
    """Load MNIST dataset and return preprocessed data"""
    (X_train, y_train), (X_test, y_test) = download_mnist()

    X_train = preprocess(X_train)
    X_test = preprocess(X_test)

    # One-hot encode labels
    y_train_onehot = np.zeros((y_train.shape[0], 10))
    y_train_onehot[np.arange(y_train.shape[0]), y_train] = 1

    y_test_onehot = np.zeros((y_test.shape[0], 10))
    y_test_onehot[np.arange(y_test.shape[0]), y_test] = 1

    return (X_train, y_train_onehot), (X_test, y_test_onehot)

def preprocess(X):
    """Normalize to [0,1] and flatten 28x28 to 784"""
    X = X.astype(np.float32) / 255.0
    X = X.reshape(X.shape[0], -1)
    return X

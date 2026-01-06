# Neural Network Visualizer

Real-time visualization of neural network training on the MNIST dataset. Watch weights, activations, and gradients update as your network learns to recognize handwritten digits.

## Features

- **Custom Neural Network**: Pure NumPy implementation with configurable architecture
- **Real-time Visualization**: Canvas-based rendering of network structure with live weight and activation updates
- **Interactive Controls**: Configure network architecture, training parameters, and control training
- **MNIST Dataset**: Automatic download and preprocessing of MNIST handwritten digits
- **WebSocket Updates**: Real-time training metrics and visualization via SocketIO
- **Edge Sampling**: Intelligent sampling of top 500 weights per layer for large networks

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

1. Start the server:
```bash
python run.py
```

2. Open your browser to:
```
http://localhost:5000
```

3. Create a network:
   - Enter hidden layer sizes (e.g., "128, 64")
   - Click "Create Network"

4. Start training:
   - Adjust epochs and batch size
   - Click "Start Training"
   - Watch the network learn in real-time!

## Architecture Overview

### Backend (`backend/`)

- **neural_net.py**: Custom neural network implementation
  - `Layer` class with forward/backward passes
  - `Network` class with training loop
  - Gradient and activation caching for visualization

- **data_loader.py**: MNIST dataset handling
  - Automatic download via TensorFlow
  - Preprocessing and normalization
  - One-hot encoding

- **trainer.py**: Training orchestration
  - Batch processing
  - Real-time metric calculation
  - SocketIO event emission

- **app.py**: Flask + SocketIO server
  - REST API for network creation and training control
  - WebSocket communication for real-time updates
  - Background thread for training

### Frontend

- **templates/index.html**: Main UI structure
- **static/css/style.css**: Dark theme styling with gradient accents
- **static/js/network-viz.js**: Canvas-based network visualization
  - Dynamic node positioning
  - Weight-based edge rendering (thickness = magnitude, color = sign)
  - Activation-based node coloring
- **static/js/socket-client.js**: WebSocket client for real-time updates
- **static/js/controls.js**: UI controls and API communication

## Visualization Details

- **Edges**:
  - Thickness proportional to weight magnitude
  - Red = positive weights, Blue = negative weights
  - Opacity based on normalized magnitude

- **Nodes**:
  - Color intensity reflects activation value
  - Brighter = higher activation

- **Edge Sampling**:
  - For layers with >500 connections, only top 500 highest magnitude weights are displayed
  - Ensures smooth performance even with large networks

## Training Metrics

Real-time display of:
- Current epoch and batch
- Training loss (cross-entropy)
- Training accuracy
- Network structure visualization

## Technical Stack

- **Backend**: Flask, Flask-SocketIO, NumPy
- **Frontend**: Vanilla JavaScript, Canvas API, Socket.IO
- **ML**: Custom NumPy neural network (no PyTorch/TensorFlow for NN)
- **Data**: TensorFlow (MNIST download only)

## Network Configuration

- **Input Layer**: 784 neurons (28×28 MNIST images)
- **Hidden Layers**: Configurable (default: 128, 64)
- **Output Layer**: 10 neurons (digits 0-9)
- **Activation**: ReLU for hidden layers, Softmax for output
- **Loss**: Cross-entropy
- **Optimizer**: Gradient descent with fixed learning rate (0.01)

## Performance

- Real-time updates every 10 batches
- Visualization runs at ~30 FPS
- Training on CPU: ~10 seconds per epoch (60,000 samples)

## Future Enhancements

- Gradient flow animation (backward pass visualization)
- Multiple optimization algorithms (Adam, RMSprop)
- Convolutional layer support
- Test set evaluation visualization
- Export trained model

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
import threading
from backend.neural_net import Network
from backend.trainer import Trainer
from backend.data_loader import load_mnist

app = Flask(__name__,
            template_folder='../templates',
            static_folder='../static')
app.config['SECRET_KEY'] = 'neural-viz-secret-key'
socketio = SocketIO(app, cors_allowed_origins="*")

# Global state
current_network = None
trainer = None
training_active = False
training_thread = None
mnist_data = None

def load_data():
    """Load MNIST data on startup"""
    global mnist_data
    if mnist_data is None:
        print("Loading MNIST dataset...")
        (X_train, y_train), (X_test, y_test) = load_mnist()
        mnist_data = {
            'X_train': X_train,
            'y_train': y_train,
            'X_test': X_test,
            'y_test': y_test
        }
        print(f"MNIST loaded: {X_train.shape[0]} training samples, {X_test.shape[0]} test samples")

@app.route('/')
def index():
    """Render main page"""
    return render_template('index.html')

@app.route('/api/create_network', methods=['POST'])
def create_network():
    """Create a new neural network"""
    global current_network

    data = request.get_json()
    layer_sizes = data.get('layer_sizes', [784, 128, 64, 10])

    # Validate layer sizes
    if not isinstance(layer_sizes, list) or len(layer_sizes) < 2:
        return jsonify({'error': 'Invalid layer sizes'}), 400

    if layer_sizes[0] != 784:
        return jsonify({'error': 'Input layer must be 784 (28x28 MNIST images)'}), 400

    if layer_sizes[-1] != 10:
        return jsonify({'error': 'Output layer must be 10 (digit classes)'}), 400

    current_network = Network(layer_sizes)

    return jsonify({
        'message': 'Network created successfully',
        'layer_sizes': layer_sizes
    })

@app.route('/api/start_training', methods=['POST'])
def start_training():
    """Start training in background thread"""
    global current_network, trainer, training_active, training_thread, mnist_data

    if current_network is None:
        return jsonify({'error': 'No network created'}), 400

    if training_active:
        return jsonify({'error': 'Training already in progress'}), 400

    # Load data if not loaded
    load_data()

    data = request.get_json()
    epochs = data.get('epochs', 10)
    batch_size = data.get('batch_size', 64)

    trainer = Trainer(current_network, socketio)
    training_active = True

    def train_background():
        global training_active
        try:
            trainer.train(
                mnist_data['X_train'],
                mnist_data['y_train'],
                epochs=epochs,
                batch_size=batch_size,
                emit_interval=10
            )
        finally:
            training_active = False

    training_thread = threading.Thread(target=train_background)
    training_thread.start()

    return jsonify({
        'message': 'Training started',
        'epochs': epochs,
        'batch_size': batch_size
    })

@app.route('/api/stop_training', methods=['POST'])
def stop_training():
    """Stop training"""
    global trainer, training_active

    if not training_active:
        return jsonify({'error': 'No training in progress'}), 400

    if trainer:
        trainer.stop()

    return jsonify({'message': 'Training stopped'})

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    print('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    print('Client disconnected')

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000, allow_unsafe_werkzeug=True)

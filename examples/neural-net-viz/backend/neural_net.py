import numpy as np


class Layer:
    def __init__(self, n_inputs, n_outputs, activation="relu"):
        self.n_inputs = n_inputs
        self.n_outputs = n_outputs
        self.activation = activation

        # Xavier initialization
        self.weights = np.random.randn(n_inputs, n_outputs) * np.sqrt(2.0 / n_inputs)
        self.biases = np.zeros(n_outputs)

        # Cache for visualization
        self.inputs = None
        self.z = None
        self.activations = None
        self.grad_weights = None
        self.grad_biases = None
        self.grad_input = None

    def forward(self, inputs):
        self.inputs = inputs
        self.z = np.dot(inputs, self.weights) + self.biases

        if self.activation == "relu":
            self.activations = np.maximum(0, self.z)
        elif self.activation == "softmax":
            exp_z = np.exp(self.z - np.max(self.z, axis=1, keepdims=True))
            self.activations = exp_z / np.sum(exp_z, axis=1, keepdims=True)
        else:
            self.activations = self.z

        return self.activations

    def backward(self, grad_output):
        if self.activation == "relu":
            grad_output = grad_output * (self.z > 0)

        batch_size = self.inputs.shape[0]
        self.grad_weights = np.dot(self.inputs.T, grad_output) / batch_size
        self.grad_biases = np.sum(grad_output, axis=0) / batch_size
        self.grad_input = np.dot(grad_output, self.weights.T)

        return self.grad_input

    def get_viz_data(self):
        return {
            "weights": self.weights.copy(),
            "biases": self.biases.copy(),
            "activations": (
                self.activations.mean(axis=0) if self.activations is not None else None
            ),
            "gradients": (
                self.grad_weights.copy() if self.grad_weights is not None else None
            ),
        }


class Network:
    def __init__(self, layer_sizes):
        self.layer_sizes = layer_sizes
        self.layers = []

        for i in range(len(layer_sizes) - 1):
            activation = "softmax" if i == len(layer_sizes) - 2 else "relu"
            layer = Layer(layer_sizes[i], layer_sizes[i + 1], activation)
            self.layers.append(layer)

    def forward(self, X):
        activations = X
        for layer in self.layers:
            activations = layer.forward(activations)
        return activations

    def backward(self, y_true):
        # Cross-entropy loss gradient for softmax output
        grad = self.layers[-1].activations - y_true

        for layer in reversed(self.layers):
            grad = layer.backward(grad)

    def train_step(self, X_batch, y_batch, learning_rate=0.01):
        # Forward pass
        predictions = self.forward(X_batch)

        # Compute loss
        loss = -np.sum(y_batch * np.log(predictions + 1e-8)) / X_batch.shape[0]

        # Backward pass
        self.backward(y_batch)

        # Update weights
        for layer in self.layers:
            layer.weights -= learning_rate * layer.grad_weights
            layer.biases -= learning_rate * layer.grad_biases

        return loss

    def get_network_viz_data(self):
        viz_data = []

        for i, layer in enumerate(self.layers):
            layer_data = layer.get_viz_data()

            # Sample top 500 weights by magnitude for visualization
            weights = layer_data["weights"]
            n_inputs, n_outputs = weights.shape

            if n_inputs * n_outputs > 500:
                # Flatten and get top indices
                flat_weights = weights.flatten()
                top_indices = np.argsort(np.abs(flat_weights))[-500:]

                sampled_edges = []
                for idx in top_indices:
                    input_idx = idx // n_outputs
                    output_idx = idx % n_outputs
                    sampled_edges.append(
                        {
                            "from": int(input_idx),
                            "to": int(output_idx),
                            "weight": float(weights[input_idx, output_idx]),
                        }
                    )
            else:
                sampled_edges = []
                for input_idx in range(n_inputs):
                    for output_idx in range(n_outputs):
                        sampled_edges.append(
                            {
                                "from": int(input_idx),
                                "to": int(output_idx),
                                "weight": float(weights[input_idx, output_idx]),
                            }
                        )

            viz_data.append(
                {
                    "layer_index": i,
                    "n_inputs": n_inputs,
                    "n_outputs": n_outputs,
                    "edges": sampled_edges,
                    "activations": (
                        layer_data["activations"].tolist()
                        if layer_data["activations"] is not None
                        else None
                    ),
                    "biases": layer_data["biases"].tolist(),
                }
            )

        return viz_data

    def predict(self, X):
        predictions = self.forward(X)
        return np.argmax(predictions, axis=1)

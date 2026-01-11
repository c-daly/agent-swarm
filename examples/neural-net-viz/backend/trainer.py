import numpy as np


class Trainer:
    def __init__(self, network, socketio):
        self.network = network
        self.socketio = socketio
        self.should_stop = False

    def train(self, X, y, epochs, batch_size, emit_interval=10):
        """Train the network and emit visualization updates"""
        self.should_stop = False
        n_samples = X.shape[0]
        n_batches = n_samples // batch_size

        for epoch in range(epochs):
            if self.should_stop:
                break

            # Shuffle data
            indices = np.random.permutation(n_samples)
            X_shuffled = X[indices]
            y_shuffled = y[indices]

            epoch_loss = 0
            correct = 0
            total = 0

            for batch_idx in range(n_batches):
                if self.should_stop:
                    break

                start_idx = batch_idx * batch_size
                end_idx = start_idx + batch_size

                X_batch = X_shuffled[start_idx:end_idx]
                y_batch = y_shuffled[start_idx:end_idx]

                # Train step
                loss = self.network.train_step(X_batch, y_batch)
                epoch_loss += loss

                # Calculate accuracy
                predictions = self.network.predict(X_batch)
                y_labels = np.argmax(y_batch, axis=1)
                correct += np.sum(predictions == y_labels)
                total += len(y_labels)

                # Emit visualization update
                if batch_idx % emit_interval == 0:
                    accuracy = correct / total if total > 0 else 0
                    viz_data = self.network.get_network_viz_data()

                    self.socketio.emit(
                        "viz_update",
                        {
                            "epoch": epoch + 1,
                            "batch": batch_idx,
                            "total_batches": n_batches,
                            "loss": float(loss),
                            "accuracy": float(accuracy),
                            "layers": viz_data,
                        },
                    )

                    self.socketio.sleep(0)  # Allow SocketIO to process

            # Emit end-of-epoch update
            avg_loss = epoch_loss / n_batches
            accuracy = correct / total

            viz_data = self.network.get_network_viz_data()
            self.socketio.emit(
                "viz_update",
                {
                    "epoch": epoch + 1,
                    "batch": n_batches,
                    "total_batches": n_batches,
                    "loss": float(avg_loss),
                    "accuracy": float(accuracy),
                    "layers": viz_data,
                },
            )

            print(
                f"Epoch {epoch + 1}/{epochs} - Loss: {avg_loss:.4f} - Accuracy: {accuracy:.4f}"
            )

        if not self.should_stop:
            self.socketio.emit(
                "training_complete", {"message": "Training completed successfully!"}
            )

    def stop(self):
        """Stop training"""
        self.should_stop = True

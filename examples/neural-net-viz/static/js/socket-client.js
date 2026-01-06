// Initialize SocketIO connection
const socket = io();

// Initialize visualizer
const visualizer = new NetworkVisualizer('network-canvas');

// Connection handlers
socket.on('connect', () => {
    console.log('Connected to server');
});

socket.on('disconnect', () => {
    console.log('Disconnected from server');
});

// Listen for visualization updates
socket.on('viz_update', (data) => {
    console.log('Received viz update:', data);

    // Update visualizer
    visualizer.drawNetwork(data);

    // Update metrics (handled by controls.js)
    window.dispatchEvent(new CustomEvent('viz_update', { detail: data }));
});

// Listen for training complete
socket.on('training_complete', (data) => {
    console.log('Training complete:', data);

    const messageEl = document.getElementById('training-message');
    messageEl.textContent = data.message;
    messageEl.classList.add('show');

    setTimeout(() => {
        messageEl.classList.remove('show');
    }, 5000);

    // Update buttons (handled by controls.js)
    window.dispatchEvent(new CustomEvent('training_complete', { detail: data }));
});

// Error handling
socket.on('error', (error) => {
    console.error('Socket error:', error);
});

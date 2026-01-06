// DOM elements
const hiddenLayersInput = document.getElementById('hidden-layers');
const createNetworkBtn = document.getElementById('create-network-btn');
const networkStatus = document.getElementById('network-status');

const epochsSlider = document.getElementById('epochs');
const epochsValue = document.getElementById('epochs-value');
const batchSizeSelect = document.getElementById('batch-size');
const startTrainingBtn = document.getElementById('start-training-btn');
const stopTrainingBtn = document.getElementById('stop-training-btn');

const currentEpoch = document.getElementById('current-epoch');
const currentBatch = document.getElementById('current-batch');
const currentLoss = document.getElementById('current-loss');
const currentAccuracy = document.getElementById('current-accuracy');

// State
let networkCreated = false;
let trainingInProgress = false;

// Epochs slider
epochsSlider.addEventListener('input', (e) => {
    epochsValue.textContent = e.target.value;
});

// Create Network
createNetworkBtn.addEventListener('click', async () => {
    const hiddenLayersText = hiddenLayersInput.value.trim();

    // Parse hidden layers
    let hiddenLayers;
    try {
        hiddenLayers = hiddenLayersText.split(',').map(s => parseInt(s.trim()));

        if (hiddenLayers.some(isNaN) || hiddenLayers.some(n => n <= 0)) {
            throw new Error('Invalid layer sizes');
        }
    } catch (e) {
        showStatus('Invalid layer sizes. Use positive integers separated by commas.', 'error');
        return;
    }

    // Build full layer sizes [784, ...hidden, 10]
    const layerSizes = [784, ...hiddenLayers, 10];

    createNetworkBtn.disabled = true;
    showStatus('Creating network...', 'success');

    try {
        const response = await fetch('/api/create_network', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ layer_sizes: layerSizes })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to create network');
        }

        showStatus(`Network created: ${layerSizes.join(' → ')}`, 'success');
        visualizer.setNetworkStructure(layerSizes);
        networkCreated = true;
        startTrainingBtn.disabled = false;

    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
    } finally {
        createNetworkBtn.disabled = false;
    }
});

// Start Training
startTrainingBtn.addEventListener('click', async () => {
    if (!networkCreated) {
        showStatus('Create a network first', 'error');
        return;
    }

    const epochs = parseInt(epochsSlider.value);
    const batchSize = parseInt(batchSizeSelect.value);

    startTrainingBtn.disabled = true;
    stopTrainingBtn.disabled = false;
    trainingInProgress = true;

    try {
        const response = await fetch('/api/start_training', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ epochs, batch_size: batchSize })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to start training');
        }

        showStatus('Training started...', 'success');

    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
        startTrainingBtn.disabled = false;
        stopTrainingBtn.disabled = true;
        trainingInProgress = false;
    }
});

// Stop Training
stopTrainingBtn.addEventListener('click', async () => {
    try {
        const response = await fetch('/api/stop_training', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to stop training');
        }

        showStatus('Training stopped', 'success');
        startTrainingBtn.disabled = false;
        stopTrainingBtn.disabled = true;
        trainingInProgress = false;

    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
    }
});

// Listen for viz updates
window.addEventListener('viz_update', (event) => {
    const data = event.detail;

    currentEpoch.textContent = `${data.epoch}`;
    currentBatch.textContent = `${data.batch}/${data.total_batches}`;
    currentLoss.textContent = data.loss.toFixed(4);
    currentAccuracy.textContent = (data.accuracy * 100).toFixed(2) + '%';
});

// Listen for training complete
window.addEventListener('training_complete', () => {
    startTrainingBtn.disabled = false;
    stopTrainingBtn.disabled = true;
    trainingInProgress = false;
});

// Helper function
function showStatus(message, type) {
    networkStatus.textContent = message;
    networkStatus.className = `status-message ${type}`;

    setTimeout(() => {
        networkStatus.textContent = '';
        networkStatus.className = 'status-message';
    }, 3000);
}

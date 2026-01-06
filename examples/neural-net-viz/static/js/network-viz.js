class NetworkVisualizer {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext('2d');
        this.layerSizes = [];
        this.nodePositions = [];
        this.currentVizData = null;
    }

    setNetworkStructure(layerSizes) {
        this.layerSizes = layerSizes;
        this.calculateNodePositions();
        this.drawNetwork(null);
    }

    calculateNodePositions() {
        this.nodePositions = [];
        const width = this.canvas.width;
        const height = this.canvas.height;
        const padding = 80;
        const usableWidth = width - 2 * padding;
        const usableHeight = height - 2 * padding;

        const numLayers = this.layerSizes.length;
        const layerSpacing = usableWidth / (numLayers - 1);

        for (let i = 0; i < numLayers; i++) {
            const layerSize = this.layerSizes[i];
            const x = padding + i * layerSpacing;
            const nodeSpacing = layerSize > 1 ? usableHeight / (layerSize - 1) : 0;
            const startY = padding + (usableHeight - (layerSize - 1) * nodeSpacing) / 2;

            const layerNodes = [];
            for (let j = 0; j < layerSize; j++) {
                const y = startY + j * nodeSpacing;
                layerNodes.push({ x, y });
            }
            this.nodePositions.push(layerNodes);
        }
    }

    drawNetwork(vizData) {
        this.currentVizData = vizData;

        // Clear canvas
        this.ctx.fillStyle = '#0a0a0a';
        this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);

        if (this.nodePositions.length === 0) {
            this.drawPlaceholder();
            return;
        }

        // Draw edges first
        this.drawEdges(vizData);

        // Draw nodes on top
        this.drawNodes(vizData);

        // Draw layer labels
        this.drawLabels();
    }

    drawPlaceholder() {
        this.ctx.fillStyle = '#666';
        this.ctx.font = '24px Arial';
        this.ctx.textAlign = 'center';
        this.ctx.fillText('Create a network to begin', this.canvas.width / 2, this.canvas.height / 2);
    }

    drawEdges(vizData) {
        if (!vizData || !vizData.layers) return;

        for (let layerIdx = 0; layerIdx < vizData.layers.length; layerIdx++) {
            const layerData = vizData.layers[layerIdx];
            const edges = layerData.edges;

            if (!edges) continue;

            const fromNodes = this.nodePositions[layerIdx];
            const toNodes = this.nodePositions[layerIdx + 1];

            // Find max weight for normalization
            let maxWeight = 0;
            for (const edge of edges) {
                maxWeight = Math.max(maxWeight, Math.abs(edge.weight));
            }

            for (const edge of edges) {
                const fromNode = fromNodes[edge.from];
                const toNode = toNodes[edge.to];

                if (!fromNode || !toNode) continue;

                const weight = edge.weight;
                const normalizedWeight = Math.abs(weight) / (maxWeight + 1e-8);

                // Color based on sign
                const color = weight >= 0 ?
                    `rgba(239, 83, 80, ${normalizedWeight * 0.6})` :  // Red for positive
                    `rgba(66, 165, 245, ${normalizedWeight * 0.6})`; // Blue for negative

                // Thickness based on magnitude
                const thickness = 0.5 + normalizedWeight * 2;

                this.ctx.strokeStyle = color;
                this.ctx.lineWidth = thickness;
                this.ctx.beginPath();
                this.ctx.moveTo(fromNode.x, fromNode.y);
                this.ctx.lineTo(toNode.x, toNode.y);
                this.ctx.stroke();
            }
        }
    }

    drawNodes(vizData) {
        for (let layerIdx = 0; layerIdx < this.nodePositions.length; layerIdx++) {
            const layerNodes = this.nodePositions[layerIdx];
            let activations = null;

            if (vizData && vizData.layers && layerIdx > 0) {
                const prevLayerData = vizData.layers[layerIdx - 1];
                if (prevLayerData && prevLayerData.activations) {
                    activations = prevLayerData.activations;
                }
            }

            for (let nodeIdx = 0; nodeIdx < layerNodes.length; nodeIdx++) {
                const node = layerNodes[nodeIdx];
                let activation = 0;

                if (activations && nodeIdx < activations.length) {
                    activation = Math.max(0, Math.min(1, activations[nodeIdx]));
                }

                // Node appearance
                const radius = 8;
                const intensity = activation;

                // Draw node
                this.ctx.beginPath();
                this.ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);

                // Fill with intensity-based color
                const baseColor = [100, 181, 246]; // Blue
                const r = Math.floor(baseColor[0] + intensity * (255 - baseColor[0]));
                const g = Math.floor(baseColor[1] + intensity * (255 - baseColor[1]));
                const b = Math.floor(baseColor[2]);

                this.ctx.fillStyle = `rgb(${r}, ${g}, ${b})`;
                this.ctx.fill();

                // Border
                this.ctx.strokeStyle = '#fff';
                this.ctx.lineWidth = 1;
                this.ctx.stroke();
            }
        }
    }

    drawLabels() {
        this.ctx.fillStyle = '#888';
        this.ctx.font = '14px Arial';
        this.ctx.textAlign = 'center';

        const labels = ['Input', ...Array(this.layerSizes.length - 2).fill('Hidden'), 'Output'];

        for (let i = 0; i < this.nodePositions.length; i++) {
            const layerNodes = this.nodePositions[i];
            if (layerNodes.length === 0) continue;

            const x = layerNodes[0].x;
            const label = `${labels[i]}\n(${this.layerSizes[i]})`;

            this.ctx.fillText(label, x, 30);
        }
    }

    animateGradients(gradientData) {
        // Optional future enhancement
    }
}

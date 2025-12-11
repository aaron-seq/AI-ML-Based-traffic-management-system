export class WebSocketService {
    private ws: WebSocket | null = null;
    private url: string;
    private messageHandlers: ((data: any) => void)[] = [];

    constructor(url: string) {
        this.url = url;
        this.connect();
    }

    private connect() {
        this.ws = new WebSocket(this.url);

        this.ws.onopen = () => {
            console.log('Connected to Traffic WebSocket');
        };

        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.messageHandlers.forEach(handler => handler(data));
            } catch (error) {
                console.error('Error parsing WebSocket message:', error);
            }
        };

        this.ws.onclose = () => {
            console.log('Traffic WebSocket disconnected');
            // Simple reconnect logic
            setTimeout(() => this.connect(), 5000);
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket Error:', error);
        };
    }

    public onMessage(handler: (data: any) => void) {
        this.messageHandlers.push(handler);
    }

    public disconnect() {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
    }
}

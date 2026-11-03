import { Component, type ReactNode } from "react";
import { InlineAlert, Button } from "@lego/connect-components-react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: "2rem", maxWidth: "600px", margin: "0 auto" }}>
          <InlineAlert variant="negative" showIcon>
            <InlineAlert.Content>
              Something went wrong: {this.state.error.message}
            </InlineAlert.Content>
          </InlineAlert>
          <div style={{ marginTop: "1rem" }}>
            <Button
              variant="neutral"
              onClick={() => this.setState({ error: null })}
            >
              Try Again
            </Button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

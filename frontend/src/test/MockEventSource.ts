export class MockEventSource extends EventTarget {
  static instances: MockEventSource[] = [];
  readyState = 0;
  constructor(readonly url: string) {
    super();
    MockEventSource.instances.push(this);
  }
  close() { this.readyState = 2; }
  snapshot(data: unknown) {
    this.readyState = 1;
    this.dispatchEvent(new MessageEvent("snapshot", { data: JSON.stringify(data) }));
  }
}

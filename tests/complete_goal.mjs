const socket = new WebSocket(process.argv[2]);
const timeout = setTimeout(() => process.exit(1), 10000);
socket.addEventListener('open', () => {
  socket.send(JSON.stringify({id: 1, method: 'initialize', params: {clientInfo: {name: 'goal-monitor-test', version: '1'}, capabilities: {experimentalApi: true}}}));
});
socket.addEventListener('message', (event) => {
  const message = JSON.parse(String(event.data));
  if (message.error) {
    console.error('隔離Goalの完了状態注入に失敗しました', message.error.code);
    process.exit(1);
  }
  if (message.id === 1) {
    socket.send(JSON.stringify({method: 'initialized'}));
    socket.send(JSON.stringify({id: 2, method: 'thread/goal/set', params: {threadId: process.argv[3], status: 'complete'}}));
  }
  if (message.id === 2) {
    clearTimeout(timeout);
    socket.close();
    console.log('隔離Goalのcompleteを設定しました');
  }
});

# gren-tvision (the JavaScript half)

The Gren package [`gilramir/gren-tvision`](../gren-tvision) is pure Gren: it can
describe a UI but cannot touch a terminal, because **Gren packages may not
declare ports**. This npm package is the other half — it takes the description
off the port and drives [`tvision-node`](../tvision-node) with it.

```
gren make Main --output=main.js
gren-tui main.js
```

or, from your own JavaScript:

```js
const run = require('gren-tvision');
run(require('./main.js'));           // options: {flags, moduleName, outPort, inPort}
```

The program must declare ports named `tuiOut` and `tuiIn` (override with
`outPort` / `inPort`). `TUI_DEBUG=/tmp/trace` logs the port conversation, which
is the only way to watch it — the terminal belongs to Turbo Vision.

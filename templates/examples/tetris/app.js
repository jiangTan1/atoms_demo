(function () {
  'use strict';

  var COLS = 10;
  var ROWS = 20;
  var CELL = 24;
  var BASE_DROP_MS = 700;

  var SHAPES = {
    I: [[0, 0, 0, 0], [1, 1, 1, 1], [0, 0, 0, 0], [0, 0, 0, 0]],
    J: [[1, 0, 0], [1, 1, 1], [0, 0, 0]],
    L: [[0, 0, 1], [1, 1, 1], [0, 0, 0]],
    O: [[1, 1], [1, 1]],
    S: [[0, 1, 1], [1, 1, 0], [0, 0, 0]],
    T: [[0, 1, 0], [1, 1, 1], [0, 0, 0]],
    Z: [[1, 1, 0], [0, 1, 1], [0, 0, 0]]
  };

  var COLORS = {
    I: '#38bdf8',
    J: '#3b82f6',
    L: '#f59e0b',
    O: '#eab308',
    S: '#22c55e',
    T: '#a855f7',
    Z: '#ef4444'
  };

  var boardCanvas = document.getElementById('board');
  var boardCtx = boardCanvas.getContext('2d');
  var nextCanvas = document.getElementById('next');
  var nextCtx = nextCanvas.getContext('2d');

  var scoreEl = document.getElementById('score');
  var linesEl = document.getElementById('lines');
  var overlay = document.getElementById('overlay');
  var overlayTitle = document.getElementById('overlayTitle');
  var overlayText = document.getElementById('overlayText');
  var startBtn = document.getElementById('startBtn');
  var restartBtn = document.getElementById('restartBtn');

  var board = createBoard();
  var piece = null;
  var nextType = randomType();
  var score = 0;
  var clearedLines = 0;
  var state = 'ready';
  var dropTimer = 0;
  var lastTime = 0;
  var rafId = 0;

  function createBoard() {
    var grid = [];
    for (var r = 0; r < ROWS; r++) {
      var row = [];
      for (var c = 0; c < COLS; c++) {
        row.push(null);
      }
      grid.push(row);
    }
    return grid;
  }

  function randomType() {
    var keys = Object.keys(SHAPES);
    return keys[Math.floor(Math.random() * keys.length)];
  }

  function makePiece(type) {
    var matrix = SHAPES[type].map(function (row) {
      return row.slice();
    });
    return {
      type: type,
      matrix: matrix,
      x: Math.floor((COLS - matrix[0].length) / 2),
      y: 0
    };
  }

  function rotateMatrix(matrix) {
    var size = matrix.length;
    var result = [];
    for (var r = 0; r < size; r++) {
      var row = [];
      for (var c = 0; c < size; c++) {
        row.push(matrix[size - 1 - c][r]);
      }
      result.push(row);
    }
    return result;
  }

  function collide(matrix, px, py) {
    for (var r = 0; r < matrix.length; r++) {
      for (var c = 0; c < matrix[r].length; c++) {
        if (!matrix[r][c]) {
          continue;
        }
        var x = px + c;
        var y = py + r;
        if (x < 0 || x >= COLS || y >= ROWS) {
          return true;
        }
        if (y >= 0 && board[y][x]) {
          return true;
        }
      }
    }
    return false;
  }

  function spawn() {
    var type = nextType;
    nextType = randomType();
    piece = makePiece(type);
    if (collide(piece.matrix, piece.x, piece.y)) {
      piece = null;
      gameOver();
      return false;
    }
    return true;
  }

  function merge() {
    for (var r = 0; r < piece.matrix.length; r++) {
      for (var c = 0; c < piece.matrix[r].length; c++) {
        if (!piece.matrix[r][c]) {
          continue;
        }
        var y = piece.y + r;
        var x = piece.x + c;
        if (y >= 0 && y < ROWS && x >= 0 && x < COLS) {
          board[y][x] = COLORS[piece.type];
        }
      }
    }
  }

  function clearLines() {
    var cleared = 0;
    for (var r = ROWS - 1; r >= 0; r--) {
      var full = true;
      for (var c = 0; c < COLS; c++) {
        if (!board[r][c]) {
          full = false;
          break;
        }
      }
      if (full) {
        board.splice(r, 1);
        var empty = [];
        for (var i = 0; i < COLS; i++) {
          empty.push(null);
        }
        board.unshift(empty);
        cleared++;
        r++;
      }
    }
    if (cleared > 0) {
      var table = [0, 100, 300, 500, 800];
      score += table[cleared] || 0;
      clearedLines += cleared;
      updateStats();
    }
  }

  function updateStats() {
    scoreEl.textContent = String(score);
    linesEl.textContent = String(clearedLines);
  }

  function dropInterval() {
    var level = Math.floor(clearedLines / 10);
    var interval = BASE_DROP_MS - level * 60;
    return interval < 120 ? 120 : interval;
  }

  function move(dx) {
    if (!piece) {
      return;
    }
    if (!collide(piece.matrix, piece.x + dx, piece.y)) {
      piece.x += dx;
      draw();
    }
  }

  function rotate() {
    if (!piece) {
      return;
    }
    var rotated = rotateMatrix(piece.matrix);
    if (!collide(rotated, piece.x, piece.y)) {
      piece.matrix = rotated;
      draw();
    }
  }

  function softDrop() {
    if (!piece) {
      return;
    }
    if (!collide(piece.matrix, piece.x, piece.y + 1)) {
      piece.y += 1;
      draw();
    } else {
      lock();
    }
  }

  function hardDrop() {
    if (!piece) {
      return;
    }
    while (!collide(piece.matrix, piece.x, piece.y + 1)) {
      piece.y += 1;
    }
    lock();
  }

  function lock() {
    merge();
    clearLines();
    if (!spawn()) {
      return;
    }
    draw();
  }

  function drawCell(ctx, x, y, color) {
    ctx.fillStyle = color;
    ctx.fillRect(x * CELL + 1, y * CELL + 1, CELL - 2, CELL - 2);
  }

  function draw() {
    boardCtx.fillStyle = '#111827';
    boardCtx.fillRect(0, 0, boardCanvas.width, boardCanvas.height);

    boardCtx.strokeStyle = 'rgba(255, 255, 255, 0.06)';
    boardCtx.lineWidth = 1;
    for (var c = 1; c < COLS; c++) {
      boardCtx.beginPath();
      boardCtx.moveTo(c * CELL, 0);
      boardCtx.lineTo(c * CELL, ROWS * CELL);
      boardCtx.stroke();
    }
    for (var g = 1; g < ROWS; g++) {
      boardCtx.beginPath();
      boardCtx.moveTo(0, g * CELL);
      boardCtx.lineTo(COLS * CELL, g * CELL);
      boardCtx.stroke();
    }

    for (var y = 0; y < ROWS; y++) {
      for (var x = 0; x < COLS; x++) {
        if (board[y][x]) {
          drawCell(boardCtx, x, y, board[y][x]);
        }
      }
    }

    if (piece) {
      var color = COLORS[piece.type];
      for (var pr = 0; pr < piece.matrix.length; pr++) {
        for (var pc = 0; pc < piece.matrix[pr].length; pc++) {
          if (piece.matrix[pr][pc]) {
            drawCell(boardCtx, piece.x + pc, piece.y + pr, color);
          }
        }
      }
    }
  }

  function drawNext() {
    nextCtx.clearRect(0, 0, nextCanvas.width, nextCanvas.height);
    var matrix = SHAPES[nextType];
    var cell = 20;
    var size = matrix.length;
    var offsetX = (nextCanvas.width - size * cell) / 2;
    var offsetY = (nextCanvas.height - size * cell) / 2;
    nextCtx.fillStyle = COLORS[nextType];
    for (var r = 0; r < size; r++) {
      for (var c = 0; c < size; c++) {
        if (matrix[r][c]) {
          nextCtx.fillRect(offsetX + c * cell + 1, offsetY + r * cell + 1, cell - 2, cell - 2);
        }
      }
    }
  }

  function loop(time) {
    if (state !== 'playing') {
      return;
    }
    if (!lastTime) {
      lastTime = time;
    }
    var delta = time - lastTime;
    lastTime = time;
    dropTimer += delta;
    if (dropTimer >= dropInterval()) {
      dropTimer = 0;
      softDrop();
    }
    if (state === 'playing') {
      rafId = window.requestAnimationFrame(loop);
    }
  }

  function stopLoop() {
    if (rafId) {
      window.cancelAnimationFrame(rafId);
      rafId = 0;
    }
  }

  function startGame() {
    stopLoop();
    board = createBoard();
    score = 0;
    clearedLines = 0;
    updateStats();
    nextType = randomType();
    state = 'playing';
    overlay.hidden = true;
    spawn();
    draw();
    drawNext();
    lastTime = 0;
    dropTimer = 0;
    if (state === 'playing') {
      rafId = window.requestAnimationFrame(loop);
    }
  }

  function gameOver() {
    state = 'over';
    stopLoop();
    overlayTitle.textContent = '游戏结束';
    overlayText.textContent = '得分 ' + score + '，消行 ' + clearedLines;
    startBtn.textContent = '再来一局';
    overlay.hidden = false;
    draw();
  }

  function onKeyDown(event) {
    var key = event.key;
    var handled = [
      'ArrowLeft', 'ArrowRight', 'ArrowDown', 'ArrowUp', ' ',
      'a', 'A', 'd', 'D', 's', 'S', 'w', 'W'
    ];
    if (handled.indexOf(key) === -1) {
      return;
    }
    event.preventDefault();
    if (state !== 'playing') {
      return;
    }
    if (key === 'ArrowLeft' || key === 'a' || key === 'A') {
      move(-1);
    } else if (key === 'ArrowRight' || key === 'd' || key === 'D') {
      move(1);
    } else if (key === 'ArrowDown' || key === 's' || key === 'S') {
      dropTimer = 0;
      softDrop();
    } else if (key === 'ArrowUp' || key === 'w' || key === 'W') {
      rotate();
    } else if (key === ' ') {
      hardDrop();
    }
  }

  document.addEventListener('keydown', onKeyDown);
  startBtn.addEventListener('click', startGame);
  restartBtn.addEventListener('click', startGame);

  draw();
  drawNext();
})();
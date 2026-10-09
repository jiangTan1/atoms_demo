(function () {
  'use strict';

  var COLS = 20;
  var ROWS = 20;
  var CELL = 20;
  var BASE_SPEED = 130;
  var MIN_SPEED = 60;

  var canvas = document.getElementById('board');
  var ctx = canvas.getContext('2d');

  var scoreEl = document.getElementById('score');
  var lengthEl = document.getElementById('length');
  var overlay = document.getElementById('overlay');
  var overlayTitle = document.getElementById('overlayTitle');
  var overlayText = document.getElementById('overlayText');
  var startBtn = document.getElementById('startBtn');
  var restartBtn = document.getElementById('restartBtn');

  var snake = [];
  var direction = { x: 1, y: 0 };
  var pendingDirection = { x: 1, y: 0 };
  var food = null;
  var score = 0;
  var speed = BASE_SPEED;
  var timer = 0;
  var state = 'ready';

  function reset() {
    snake = [
      { x: 9, y: 10 },
      { x: 8, y: 10 },
      { x: 7, y: 10 }
    ];
    direction = { x: 1, y: 0 };
    pendingDirection = { x: 1, y: 0 };
    score = 0;
    speed = BASE_SPEED;
    placeFood();
    updateStats();
  }

  function occupied(x, y) {
    for (var i = 0; i < snake.length; i++) {
      if (snake[i].x === x && snake[i].y === y) {
        return true;
      }
    }
    return false;
  }

  function placeFood() {
    var empty = [];
    for (var y = 0; y < ROWS; y++) {
      for (var x = 0; x < COLS; x++) {
        if (!occupied(x, y)) {
          empty.push({ x: x, y: y });
        }
      }
    }
    if (!empty.length) {
      food = null;
      return;
    }
    food = empty[Math.floor(Math.random() * empty.length)];
  }

  function updateStats() {
    scoreEl.textContent = String(score);
    lengthEl.textContent = String(snake.length);
  }

  function startTimer() {
    clearInterval(timer);
    timer = setInterval(step, speed);
  }

  function stopTimer() {
    clearInterval(timer);
    timer = 0;
  }

  function step() {
    if (state !== 'playing') {
      return;
    }

    direction = pendingDirection;
    var head = { x: snake[0].x + direction.x, y: snake[0].y + direction.y };

    if (head.x < 0 || head.x >= COLS || head.y < 0 || head.y >= ROWS) {
      gameOver();
      return;
    }
    for (var i = 0; i < snake.length - 1; i++) {
      if (snake[i].x === head.x && snake[i].y === head.y) {
        gameOver();
        return;
      }
    }

    snake.unshift(head);

    if (food && head.x === food.x && head.y === food.y) {
      score += 10;
      if (speed > MIN_SPEED) {
        speed -= 4;
      }
      placeFood();
      updateStats();
      startTimer();
    } else {
      snake.pop();
    }

    draw();
  }

  function draw() {
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
    ctx.lineWidth = 1;
    for (var c = 1; c < COLS; c++) {
      ctx.beginPath();
      ctx.moveTo(c * CELL, 0);
      ctx.lineTo(c * CELL, ROWS * CELL);
      ctx.stroke();
    }
    for (var r = 1; r < ROWS; r++) {
      ctx.beginPath();
      ctx.moveTo(0, r * CELL);
      ctx.lineTo(COLS * CELL, r * CELL);
      ctx.stroke();
    }

    if (food) {
      ctx.fillStyle = '#f97316';
      ctx.beginPath();
      ctx.arc(food.x * CELL + CELL / 2, food.y * CELL + CELL / 2, CELL / 2 - 2, 0, Math.PI * 2);
      ctx.fill();
    }

    for (var i = 0; i < snake.length; i++) {
      ctx.fillStyle = i === 0 ? '#4ade80' : '#16a34a';
      ctx.fillRect(snake[i].x * CELL + 1, snake[i].y * CELL + 1, CELL - 2, CELL - 2);
    }
  }

  function startGame() {
    reset();
    state = 'playing';
    overlay.hidden = true;
    startTimer();
    draw();
  }

  function gameOver() {
    state = 'over';
    stopTimer();
    overlayTitle.textContent = '游戏结束';
    overlayText.textContent = '得分 ' + score + '，蛇长 ' + snake.length;
    startBtn.textContent = '再来一局';
    overlay.hidden = false;
    draw();
  }

  function onKeyDown(event) {
    var map = {
      ArrowLeft: { x: -1, y: 0 },
      a: { x: -1, y: 0 },
      A: { x: -1, y: 0 },
      ArrowRight: { x: 1, y: 0 },
      d: { x: 1, y: 0 },
      D: { x: 1, y: 0 },
      ArrowUp: { x: 0, y: -1 },
      w: { x: 0, y: -1 },
      W: { x: 0, y: -1 },
      ArrowDown: { x: 0, y: 1 },
      s: { x: 0, y: 1 },
      S: { x: 0, y: 1 }
    };
    var next = map[event.key];
    if (!next) {
      return;
    }
    event.preventDefault();
    if (state !== 'playing') {
      return;
    }
    if (next.x === -direction.x && next.y === -direction.y) {
      return;
    }
    pendingDirection = next;
  }

  document.addEventListener('keydown', onKeyDown);
  startBtn.addEventListener('click', startGame);
  restartBtn.addEventListener('click', startGame);

  reset();
  draw();
})();
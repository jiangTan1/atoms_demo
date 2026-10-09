(function () {
  'use strict';

  var SIZE = 4;

  var board = [];
  var score = 0;
  var won = false;
  var over = false;
  var bannerAction = null;

  var gridEl = document.getElementById('grid');
  var scoreEl = document.getElementById('score');
  var bestEl = document.getElementById('best');
  var banner = document.getElementById('banner');
  var bannerTitle = document.getElementById('bannerTitle');
  var bannerText = document.getElementById('bannerText');
  var bannerBtn = document.getElementById('bannerBtn');
  var restartBtn = document.getElementById('restartBtn');

  var cells = [];

  function buildGrid() {
    gridEl.innerHTML = '';
    cells = [];
    for (var i = 0; i < SIZE * SIZE; i++) {
      var cell = document.createElement('div');
      cell.className = 'cell';
      var span = document.createElement('span');
      span.className = 'cell-value';
      cell.appendChild(span);
      gridEl.appendChild(cell);
      cells.push(span);
    }
  }

  function emptyBoard() {
    var b = [];
    for (var r = 0; r < SIZE; r++) {
      var row = [];
      for (var c = 0; c < SIZE; c++) {
        row.push(0);
      }
      b.push(row);
    }
    return b;
  }

  function startGame() {
    board = emptyBoard();
    score = 0;
    won = false;
    over = false;
    banner.hidden = true;
    bannerAction = null;
    addRandomTile();
    addRandomTile();
    render();
  }

  function addRandomTile() {
    var spots = [];
    for (var r = 0; r < SIZE; r++) {
      for (var c = 0; c < SIZE; c++) {
        if (board[r][c] === 0) {
          spots.push({ r: r, c: c });
        }
      }
    }
    if (!spots.length) {
      return;
    }
    var spot = spots[Math.floor(Math.random() * spots.length)];
    board[spot.r][spot.c] = Math.random() < 0.9 ? 2 : 4;
  }

  function render() {
    var max = 0;
    for (var r = 0; r < SIZE; r++) {
      for (var c = 0; c < SIZE; c++) {
        var value = board[r][c];
        var span = cells[r * SIZE + c];
        span.textContent = value === 0 ? '' : String(value);
        span.parentNode.className = value === 0 ? 'cell' : 'cell tile tile-' + tileClass(value);
        if (value > max) {
          max = value;
        }
      }
    }
    scoreEl.textContent = String(score);
    bestEl.textContent = String(max);
  }

  function tileClass(value) {
    return value > 2048 ? 'super' : String(value);
  }

  function slide(row) {
    var nums = [];
    for (var i = 0; i < row.length; i++) {
      if (row[i] !== 0) {
        nums.push(row[i]);
      }
    }
    var result = [];
    var gained = 0;
    for (var j = 0; j < nums.length; j++) {
      if (nums[j] === nums[j + 1]) {
        var merged = nums[j] * 2;
        result.push(merged);
        gained += merged;
        j++;
      } else {
        result.push(nums[j]);
      }
    }
    while (result.length < SIZE) {
      result.push(0);
    }
    return { row: result, gained: gained };
  }

  function move(dir) {
    if (over) {
      return;
    }
    var moved = false;
    var gained = 0;

    if (dir === 'left' || dir === 'right') {
      for (var r = 0; r < SIZE; r++) {
        var row = board[r].slice();
        if (dir === 'right') {
          row.reverse();
        }
        var res = slide(row);
        var out = res.row;
        if (dir === 'right') {
          out = out.slice().reverse();
        }
        if (out.join(',') !== board[r].join(',')) {
          board[r] = out;
          moved = true;
        }
        gained += res.gained;
      }
    } else {
      for (var c = 0; c < SIZE; c++) {
        var col = [];
        for (var rr = 0; rr < SIZE; rr++) {
          col.push(board[rr][c]);
        }
        if (dir === 'down') {
          col.reverse();
        }
        var resCol = slide(col);
        var outCol = resCol.row;
        if (dir === 'down') {
          outCol = outCol.slice().reverse();
        }
        for (var r2 = 0; r2 < SIZE; r2++) {
          if (board[r2][c] !== outCol[r2]) {
            board[r2][c] = outCol[r2];
            moved = true;
          }
        }
        gained += resCol.gained;
      }
    }

    if (!moved) {
      return;
    }

    score += gained;
    addRandomTile();
    render();
    checkState();
  }

  function checkState() {
    var max = 0;
    for (var r = 0; r < SIZE; r++) {
      for (var c = 0; c < SIZE; c++) {
        if (board[r][c] > max) {
          max = board[r][c];
        }
      }
    }

    if (!won && max >= 2048) {
      won = true;
      showBanner('达成 2048！', '可以继续挑战更大的数字。', '继续游戏', null);
      return;
    }

    if (!canMove()) {
      over = true;
      showBanner('游戏结束', '得分 ' + score + '，已没有可移动的方块。', '再来一局', startGame);
    }
  }

  function canMove() {
    for (var r = 0; r < SIZE; r++) {
      for (var c = 0; c < SIZE; c++) {
        if (board[r][c] === 0) {
          return true;
        }
        if (c + 1 < SIZE && board[r][c] === board[r][c + 1]) {
          return true;
        }
        if (r + 1 < SIZE && board[r][c] === board[r + 1][c]) {
          return true;
        }
      }
    }
    return false;
  }

  function showBanner(title, text, label, action) {
    bannerTitle.textContent = title;
    bannerText.textContent = text;
    bannerBtn.textContent = label;
    bannerAction = action;
    banner.hidden = false;
  }

  function onKeyDown(event) {
    var map = {
      ArrowLeft: 'left',
      a: 'left',
      A: 'left',
      ArrowRight: 'right',
      d: 'right',
      D: 'right',
      ArrowUp: 'up',
      w: 'up',
      W: 'up',
      ArrowDown: 'down',
      s: 'down',
      S: 'down'
    };
    var dir = map[event.key];
    if (!dir) {
      return;
    }
    event.preventDefault();
    move(dir);
  }

  bannerBtn.addEventListener('click', function () {
    banner.hidden = true;
    if (bannerAction) {
      var action = bannerAction;
      bannerAction = null;
      action();
    }
  });
  document.addEventListener('keydown', onKeyDown);
  restartBtn.addEventListener('click', startGame);

  buildGrid();
  startGame();
})();
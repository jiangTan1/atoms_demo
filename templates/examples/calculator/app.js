(function () {
  'use strict';

  var OP_TEXT = { '+': '+', '-': '−', '*': '×', '/': '÷' };

  var exprEl = document.getElementById('expr');
  var valueEl = document.getElementById('value');
  var keysEl = document.getElementById('keys');
  var restartBtn = document.getElementById('restartBtn');

  var current = '0';
  var first = null;
  var operator = null;
  var waiting = false;
  var evaluated = false;
  var errored = false;

  function reset() {
    current = '0';
    first = null;
    operator = null;
    waiting = false;
    evaluated = false;
    errored = false;
    render();
  }

  function render() {
    valueEl.textContent = current;
    if (operator !== null && first !== null) {
      exprEl.textContent = formatNumber(first) + ' ' + OP_TEXT[operator];
    } else {
      exprEl.textContent = '';
    }
  }

  function formatNumber(n) {
    if (!isFinite(n)) {
      return '错误';
    }
    var rounded = parseFloat(n.toPrecision(12));
    return String(rounded);
  }

  function inputDigit(digit) {
    if (errored) {
      reset();
    }
    if (evaluated) {
      current = '0';
      evaluated = false;
    }
    if (waiting) {
      current = digit;
      waiting = false;
    } else if (current === '0') {
      current = digit;
    } else {
      current += digit;
    }
    render();
  }

  function inputDot() {
    if (errored) {
      reset();
    }
    if (evaluated) {
      current = '0';
      evaluated = false;
    }
    if (waiting) {
      current = '0.';
      waiting = false;
    } else if (current.indexOf('.') === -1) {
      current += '.';
    }
    render();
  }

  function chooseOperator(nextOp) {
    if (errored) {
      return;
    }
    evaluated = false;
    var value = parseFloat(current);

    if (operator !== null && waiting) {
      operator = nextOp;
      render();
      return;
    }

    if (first === null) {
      first = value;
    } else if (operator !== null) {
      var result = calculate(first, value, operator);
      if (result === null) {
        showError();
        return;
      }
      first = result;
      current = formatNumber(result);
    }

    operator = nextOp;
    waiting = true;
    render();
  }

  function equals() {
    if (errored || operator === null || first === null) {
      return;
    }
    var value = parseFloat(current);
    var result = calculate(first, value, operator);
    if (result === null) {
      showError();
      return;
    }
    current = formatNumber(result);
    first = null;
    operator = null;
    waiting = false;
    evaluated = true;
    render();
  }

  function calculate(a, b, op) {
    var result;
    if (op === '+') {
      result = a + b;
    } else if (op === '-') {
      result = a - b;
    } else if (op === '*') {
      result = a * b;
    } else if (op === '/') {
      if (b === 0) {
        return null;
      }
      result = a / b;
    } else {
      return null;
    }
    if (!isFinite(result)) {
      return null;
    }
    return result;
  }

  function percent() {
    if (errored) {
      return;
    }
    var value = parseFloat(current) / 100;
    current = formatNumber(value);
    evaluated = false;
    render();
  }

  function toggleSign() {
    if (errored || current === '0') {
      return;
    }
    if (current.charAt(0) === '-') {
      current = current.slice(1);
    } else {
      current = '-' + current;
    }
    render();
  }

  function backspace() {
    if (errored) {
      reset();
      return;
    }
    if (waiting || evaluated) {
      return;
    }
    if (current.length <= 1) {
      current = '0';
    } else {
      current = current.slice(0, -1);
    }
    if (current === '-' || current === '') {
      current = '0';
    }
    render();
  }

  function showError() {
    current = '错误';
    first = null;
    operator = null;
    waiting = false;
    evaluated = false;
    errored = true;
    exprEl.textContent = '';
    valueEl.textContent = current;
  }

  function handleAction(action) {
    if (action === 'clear') {
      reset();
    } else if (action === 'back') {
      backspace();
    } else if (action === 'percent') {
      percent();
    } else if (action === 'sign') {
      toggleSign();
    } else if (action === 'dot') {
      inputDot();
    } else if (action === 'equals') {
      equals();
    }
  }

  keysEl.addEventListener('click', function (event) {
    var btn = event.target.closest('button');
    if (!btn) {
      return;
    }
    var digit = btn.getAttribute('data-digit');
    if (digit !== null) {
      inputDigit(digit);
      return;
    }
    var op = btn.getAttribute('data-op');
    if (op !== null) {
      chooseOperator(op);
      return;
    }
    handleAction(btn.getAttribute('data-action'));
  });

  document.addEventListener('keydown', function (event) {
    var key = event.key;
    if (/^[0-9]$/.test(key)) {
      inputDigit(key);
    } else if (key === '.') {
      inputDot();
    } else if (key === '+' || key === '-' || key === '*' || key === '/') {
      chooseOperator(key);
    } else if (key === 'Enter' || key === '=') {
      equals();
    } else if (key === 'Backspace') {
      backspace();
    } else if (key === 'Escape') {
      reset();
    } else if (key === '%') {
      percent();
    } else {
      return;
    }
    event.preventDefault();
  });

  restartBtn.addEventListener('click', reset);

  reset();
})();
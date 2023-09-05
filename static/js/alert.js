closeBtn = document.querySelector('.close');
alertBtn = document.querySelector('.alert');
closeBtn.addEventListener('click', () => {
  alertBtn.style.display = 'none';
});
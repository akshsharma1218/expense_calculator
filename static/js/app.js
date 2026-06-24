document.addEventListener('DOMContentLoaded', function () {
  const navbar = document.querySelector('.navbar');
  if (navbar) {
    document.addEventListener('scroll', () => {
      navbar.classList.toggle('scrolled', window.scrollY > 8);
    });
  }

  document.querySelectorAll('[data-animate]').forEach((el, index) => {
    el.style.transitionDelay = `${index * 60}ms`;
  });
});

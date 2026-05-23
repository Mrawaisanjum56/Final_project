(function () {
    const passwordFields = document.querySelectorAll('input[type="password"]');
    passwordFields.forEach(function (input) {
        const wrapper = document.createElement('div');
        wrapper.className = 'password-toggle-wrap';
        input.parentNode.insertBefore(wrapper, input);
        wrapper.appendChild(input);

        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'password-toggle-btn';
        button.innerHTML = '<i class="fas fa-eye"></i>';
        button.setAttribute('aria-label', 'Show password');
        button.addEventListener('click', function () {
            const isHidden = input.type === 'password';
            input.type = isHidden ? 'text' : 'password';
            button.innerHTML = isHidden ? '<i class="fas fa-eye-slash"></i>' : '<i class="fas fa-eye"></i>';
            button.setAttribute('aria-label', isHidden ? 'Hide password' : 'Show password');
        });
        wrapper.appendChild(button);
    });
})();

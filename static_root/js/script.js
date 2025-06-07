document.addEventListener('DOMContentLoaded', function () {
    const modal = new bootstrap.Modal(document.getElementById('portfolioModal'));
    const portfolioLinks = document.querySelectorAll('.portfolio-link');
    const modalTitle = document.getElementById('portfolioModalLabel');
    const addToCartButton = document.getElementById('addToCartButton');
    let selectedItem = {};

    portfolioLinks.forEach(link => {
        link.addEventListener('click', function (event) {
            const itemTitle = link.getAttribute('data-item');
            modalTitle.textContent = itemTitle;
            selectedItem = {
                title: itemTitle,
                type: 'Standard',
                quantity: 1
            };
            modal.show();
        });
    });

    document.getElementById('itemType').addEventListener('change', function (event) {
        selectedItem.type = event.target.value;
    });

    document.getElementById('itemQuantity').addEventListener('input', function (event) {
        selectedItem.quantity = parseInt(event.target.value);
    });

    addToCartButton.addEventListener('click', function () {
        addToCart(selectedItem);
        modal.hide();
    });

    function addToCart(item) {
        console.log('Item added to cart:', item);
        // Here you can add the code to actually add the item to the cart
    }
});


/**
 * Module Tính Tiền Đơn Hàng (CSMS Billing Calculator)
 */

/**
 * Tính toán tổng tiền hóa đơn dựa trên danh sách sản phẩm, giảm giá và VAT.
 *
 * @param {Array} items - Danh sách sản phẩm: [{ id, name, price, quantity, discountPercent }]
 * @param {Object} options - Tùy chọn: { globalVoucherPercent: number, vatPercent: number }
 * @returns {Object} Kết quả chi tiết hóa đơn
 */
function calculateInvoice(items = [], options = {}) {
  const vatPercent = options.vatPercent !== undefined ? options.vatPercent : 10; // Mặc định 10% VAT
  const globalVoucherPercent = options.globalVoucherPercent || 0; // Giảm giá voucher tổng (%)

  let subtotal = 0; // Tổng tiền hàng chưa giảm giá
  let itemDiscountTotal = 0; // Tổng giảm giá theo từng món

  const detailedItems = items.map((item) => {
    const itemSubtotal = item.price * item.quantity;
    const itemDiscount = Math.round(
      itemSubtotal * ((item.discountPercent || 0) / 100),
    );
    const itemTotal = itemSubtotal - itemDiscount;

    subtotal += itemSubtotal;
    itemDiscountTotal += itemDiscount;

    return {
      ...item,
      itemSubtotal,
      itemDiscount,
      itemTotal,
    };
  });

  // Tiền sau khi giảm giá riêng từng item
  const amountAfterItemDiscount = subtotal - itemDiscountTotal;

  // Giảm giá từ Voucher tổng
  const globalVoucherDiscount = Math.round(
    amountAfterItemDiscount * (globalVoucherPercent / 100),
  );

  // Tổng tiền trước VAT
  const amountBeforeVAT = amountAfterItemDiscount - globalVoucherDiscount;

  // Tiền thuế VAT
  const vatAmount = Math.round(amountBeforeVAT * (vatPercent / 100));

  // Tổng tiền thanh toán cuối cùng
  const totalAmount = amountBeforeVAT + vatAmount;

  return {
    subtotal,
    itemDiscountTotal,
    globalVoucherDiscount,
    amountBeforeVAT,
    vatAmount,
    totalAmount,
    items: detailedItems,
  };
}

module.exports = { calculateInvoice };

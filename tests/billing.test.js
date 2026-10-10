const { calculateInvoice } = require("../src/billing");

/**
 * CA KIỂM THỬ T-77 & T-78: BỘ CA KIỂM THỬ TÍNH TIỀN VỚI ĐÁP ÁN TÍNH TAY
 */
describe("S-32 — Bộ ca kiểm thử tính tiền (T-77 & T-78)", () => {
  // ==========================================
  // ĐỢT 1: 3 CA ĐẦU (Nộp trước hết Ngày 2)
  // ==========================================

  test("Ca 1 (T-77/Ca 1): Đơn hàng cơ bản không giảm giá, VAT 10%", () => {
    // Input
    const items = [
      { id: "P01", name: "Sữa tươi", price: 15000, quantity: 2 },
      { id: "P02", name: "Bánh mì", price: 20000, quantity: 1 },
    ];
    const options = { vatPercent: 10, globalVoucherPercent: 0 };

    // Đáp án tính tay T-77:
    // Subtotal = (15000 * 2) + (20000 * 1) = 50,000 VNĐ
    // Item Discount = 0
    // Voucher Discount = 0
    // Before VAT = 50,000 VNĐ
    // VAT (10%) = 5,000 VNĐ
    // Total Amount = 55,000 VNĐ

    const result = calculateInvoice(items, options);

    expect(result.subtotal).toBe(50000);
    expect(result.itemDiscountTotal).toBe(0);
    expect(result.globalVoucherDiscount).toBe(0);
    expect(result.vatAmount).toBe(5000);
    expect(result.totalAmount).toBe(55000);
  });

  test("Ca 2 (T-77/Ca 2): Đơn hàng có giảm giá riêng theo từng sản phẩm", () => {
    // Input
    const items = [
      {
        id: "P01",
        name: "Nước ngọt",
        price: 10000,
        quantity: 5,
        discountPercent: 10,
      }, // 50,000 - 5,000 = 45,000
      {
        id: "P02",
        name: "Mì tôm",
        price: 5000,
        quantity: 10,
        discountPercent: 20,
      }, // 50,000 - 10,000 = 40,000
    ];
    const options = { vatPercent: 10, globalVoucherPercent: 0 };

    // Đáp án tính tay T-77:
    // Subtotal = 100,000 VNĐ
    // Item Discount = 5,000 + 10,000 = 15,000 VNĐ
    // Before VAT = 85,000 VNĐ
    // VAT (10%) = 8,500 VNĐ
    // Total Amount = 93,500 VNĐ

    const result = calculateInvoice(items, options);

    expect(result.subtotal).toBe(100000);
    expect(result.itemDiscountTotal).toBe(15000);
    expect(result.vatAmount).toBe(8500);
    expect(result.totalAmount).toBe(93500);
  });

  test("Ca 3 (T-77/Ca 3): Đơn hàng áp dụng Voucher tổng 5% và VAT 8%", () => {
    // Input
    const items = [
      { id: "P03", name: "Cà phê đóng chai", price: 30000, quantity: 2 }, // 60,000
    ];
    const options = { vatPercent: 8, globalVoucherPercent: 5 };

    // Đáp án tính tay T-77:
    // Subtotal = 60,000 VNĐ
    // Voucher Discount (5%) = 60,000 * 0.05 = 3,000 VNĐ
    // Before VAT = 57,000 VNĐ
    // VAT (8%) = 57,000 * 0.08 = 4,560 VNĐ
    // Total Amount = 61,560 VNĐ

    const result = calculateInvoice(items, options);

    expect(result.subtotal).toBe(60000);
    expect(result.globalVoucherDiscount).toBe(3000);
    expect(result.vatAmount).toBe(4560);
    expect(result.totalAmount).toBe(61560);
  });

  // ==========================================
  // ĐỢT 2: CÁC CA CÒN LẠI (Nộp trước hết Ngày 3)
  // ==========================================

  test("Ca 4 (T-77/Ca 4): Kết hợp giảm giá sản phẩm, Voucher tổng và làm tròn tiền", () => {
    const items = [
      {
        id: "P04",
        name: "Khăn giấy",
        price: 12500,
        quantity: 3,
        discountPercent: 15,
      }, // 37,500 - 5,625 = 31,875
    ];
    const options = { vatPercent: 10, globalVoucherPercent: 10 };

    // Đáp án tính tay T-77:
    // Subtotal = 37,500
    // Item Discount = Math.round(37500 * 0.15) = 5,625
    // Amount after Item Discount = 31,875
    // Voucher Discount = Math.round(31875 * 0.10) = 3,188
    // Before VAT = 31,875 - 3,188 = 28,687
    // VAT (10%) = Math.round(28687 * 0.10) = 2,869
    // Total Amount = 28,687 + 2,869 = 31,556 VNĐ

    const result = calculateInvoice(items, options);

    expect(result.subtotal).toBe(37500);
    expect(result.itemDiscountTotal).toBe(5625);
    expect(result.globalVoucherDiscount).toBe(3188);
    expect(result.vatAmount).toBe(2869);
    expect(result.totalAmount).toBe(31556);
  });

  test("Ca 5 (T-77/Ca 5): Đơn hàng trống (Edge case)", () => {
    const items = [];
    const options = { vatPercent: 10, globalVoucherPercent: 10 };

    const result = calculateInvoice(items, options);

    expect(result.subtotal).toBe(0);
    expect(result.totalAmount).toBe(0);
  });
});

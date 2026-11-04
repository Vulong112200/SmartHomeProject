import 'package:flutter_test/flutter_test.dart';

import 'package:frontend/core/device_type.dart';

void main() {
  test('category chủ nhà đặt thắng suy diễn từ tên', () {
    // Tên chứa "cửa" nhưng chủ nhà đã đặt là máy cho ăn.
    expect(deviceTypeOf('Cửa hàng hạt', category: 'feeder'), DeviceType.feeder);
    expect(deviceTypeOf('Thiết bị A', category: 'purifier'), DeviceType.airPurifier);
    expect(deviceTypeOf('Thiết bị B', category: 'curtain'), DeviceType.curtain);
  });

  test('category null hoặc lạ thì suy từ tên như cũ', () {
    expect(deviceTypeOf('Cửa cuốn'), DeviceType.curtain);
    expect(deviceTypeOf('Lọc không khí Core 300S', category: null), DeviceType.airPurifier);
    expect(deviceTypeOf('Máy cho mèo ăn tự động', category: 'toaster'), DeviceType.feeder);
    expect(deviceTypeOf('Đèn ngủ'), DeviceType.unknown);
  });

  test('máy bơm tăng áp là công tắc, KHÔNG phải máy cho ăn', () {
    // "tăng áp" chứa chuỗi "ăn" — từ khóa của máy cho ăn.
    expect(deviceTypeOf('Tăng áp (Home)'), DeviceType.powerSwitch);
    expect(deviceTypeOf('Máy bơm tăng áp'), DeviceType.powerSwitch);
    expect(deviceTypeOf('Thiết bị C', category: 'switch'), DeviceType.powerSwitch);
  });

  test('mọi category có nhãn hiển thị', () {
    expect(deviceCategoryLabels.keys.toSet(), deviceCategories.keys.toSet());
  });
}

// lib/theme/app_colors.dart
import 'package:flutter/material.dart';

/// Bảng màu của app, có bản TỐI (giữ nguyên màu gốc) và bản SÁNG.
///
/// Gắn vào ThemeData qua `extensions`, đọc bằng `context.palette.x` — đổi
/// sáng/tối là MaterialApp đổi theme, mọi widget đọc palette tự vẽ lại.
/// Trước đây là hằng số `AppColors.x` nên app chỉ có thể tối.
@immutable
class AppPalette extends ThemeExtension<AppPalette> {
  // Backgrounds
  final Color background;
  final Color surface;
  final Color card;
  final Color cardLight;

  // Accents & Glows
  final Color primary;
  final Color cyan;
  final Color purple;
  final Color success;

  // Text
  final Color textMain;
  final Color textSub;

  /// Viền/đường kẻ mảnh (trước đây viết cứng `Colors.white10` — vô hình trên nền sáng).
  final Color outline;

  const AppPalette({
    required this.background,
    required this.surface,
    required this.card,
    required this.cardLight,
    required this.primary,
    required this.cyan,
    required this.purple,
    required this.success,
    required this.textMain,
    required this.textSub,
    required this.outline,
  });

  static const dark = AppPalette(
    background: Color(0xFF121212),
    surface: Color(0xFF181A20),
    card: Color(0xFF242731),
    cardLight: Color(0xFF2A2D38),
    primary: Color(0xFF4DA3FF), // Blue
    cyan: Color(0xFF5ED6FF),
    purple: Color(0xFF7B61FF),
    success: Color(0xFF4ADE80), // Green
    textMain: Color(0xFFF8F9FA), // Trắng ngà
    textSub: Color(0xFFA0A0AB), // Xám nhạt
    outline: Colors.white10,
  );

  // Màu nhấn đậm hơn bản tối: xanh #4DA3FF trên nền trắng chỉ đạt ~2.6:1, chữ khó đọc.
  static const light = AppPalette(
    background: Color(0xFFF3F4F8),
    surface: Color(0xFFFFFFFF),
    card: Color(0xFFFFFFFF),
    cardLight: Color(0xFFE8EAF0),
    primary: Color(0xFF1F6FD1),
    cyan: Color(0xFF0B8FB3),
    purple: Color(0xFF6246EA),
    success: Color(0xFF15803D),
    textMain: Color(0xFF1A1C23),
    textSub: Color(0xFF5E6170),
    outline: Color(0x1F000000),
  );

  LinearGradient get primaryGradient => LinearGradient(
        colors: [primary, purple],
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
      );

  @override
  AppPalette copyWith({
    Color? background,
    Color? surface,
    Color? card,
    Color? cardLight,
    Color? primary,
    Color? cyan,
    Color? purple,
    Color? success,
    Color? textMain,
    Color? textSub,
    Color? outline,
  }) {
    return AppPalette(
      background: background ?? this.background,
      surface: surface ?? this.surface,
      card: card ?? this.card,
      cardLight: cardLight ?? this.cardLight,
      primary: primary ?? this.primary,
      cyan: cyan ?? this.cyan,
      purple: purple ?? this.purple,
      success: success ?? this.success,
      textMain: textMain ?? this.textMain,
      textSub: textSub ?? this.textSub,
      outline: outline ?? this.outline,
    );
  }

  @override
  AppPalette lerp(ThemeExtension<AppPalette>? other, double t) {
    if (other is! AppPalette) return this;
    return AppPalette(
      background: Color.lerp(background, other.background, t)!,
      surface: Color.lerp(surface, other.surface, t)!,
      card: Color.lerp(card, other.card, t)!,
      cardLight: Color.lerp(cardLight, other.cardLight, t)!,
      primary: Color.lerp(primary, other.primary, t)!,
      cyan: Color.lerp(cyan, other.cyan, t)!,
      purple: Color.lerp(purple, other.purple, t)!,
      success: Color.lerp(success, other.success, t)!,
      textMain: Color.lerp(textMain, other.textMain, t)!,
      textSub: Color.lerp(textSub, other.textSub, t)!,
      outline: Color.lerp(outline, other.outline, t)!,
    );
  }
}

extension AppPaletteX on BuildContext {
  /// Bảng màu của theme hiện tại (sáng/tối). Thiếu extension -> bản tối.
  AppPalette get palette => Theme.of(this).extension<AppPalette>() ?? AppPalette.dark;
}

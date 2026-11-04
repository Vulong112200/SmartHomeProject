// lib/theme/app_theme.dart
import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'app_colors.dart';

class AppTheme {
  static ThemeData get darkTheme => _build(AppPalette.dark, Brightness.dark);
  static ThemeData get lightTheme => _build(AppPalette.light, Brightness.light);

  static ThemeData _build(AppPalette p, Brightness brightness) {
    final base = brightness == Brightness.dark ? ThemeData.dark() : ThemeData.light();
    return ThemeData(
      useMaterial3: true,
      brightness: brightness,
      scaffoldBackgroundColor: p.background,
      // Giữ đúng ColorScheme cũ cho bản tối (giao diện quen thuộc không đổi).
      colorScheme: brightness == Brightness.dark
          ? ColorScheme.dark(primary: p.primary, surface: p.surface)
          : ColorScheme.light(primary: p.primary, surface: p.surface),
      textTheme: GoogleFonts.interTextTheme(base.textTheme).copyWith(
        bodyLarge: TextStyle(color: p.textMain),
        bodyMedium: TextStyle(color: p.textSub),
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: Colors.transparent,
        elevation: 0,
        centerTitle: false,
      ),
      extensions: [p],
    );
  }
}

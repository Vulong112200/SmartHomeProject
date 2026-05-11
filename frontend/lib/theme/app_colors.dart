// lib/theme/app_colors.dart
import 'package:flutter/material.dart';

class AppColors {
  // Backgrounds
  static const Color background = Color(0xFF121212);
  static const Color surface = Color(0xFF181A20);
  static const Color card = Color(0xFF242731);
  static const Color cardLight = Color(0xFF2A2D38);

  // Accents & Glows
  static const Color primary = Color(0xFF4DA3FF); // Blue
  static const Color cyan = Color(0xFF5ED6FF);
  static const Color purple = Color(0xFF7B61FF);
  static const Color success = Color(0xFF4ADE80); // Green

  // Text
  static const Color textMain = Color(0xFFF8F9FA); // Trắng ngà
  static const Color textSub = Color(0xFFA0A0AB);  // Xám nhạt

  // Gradients
  static const LinearGradient primaryGradient = LinearGradient(
    colors: [primary, purple],
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
  );
}
plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("dev.flutter.flutter-gradle-plugin")
}

android {
    namespace = "com.example.frontend"
    // 1. Nâng SDK lên 36 để chiều lòng speech_to_text
    compileSdk = 36

    ndkVersion = flutter.ndkVersion
    
    defaultConfig {
        applicationId = "com.example.frontend"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        release {
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    // 2. Gom compileOptions về 1 chỗ duy nhất
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    // 3. Sử dụng chuẩn compilerOptions mới của Kotlin DSL
    kotlin {
        compilerOptions {
            jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
        }
    }
}

flutter {
    source = "../.."
}

dependencies {
    // Cần cho ShortcutManagerCompat / ShortcutInfoCompat (pinned shortcut).
    implementation("androidx.core:core-ktx:1.13.1")
}
plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

android {
    namespace = "io.dressup"
    compileSdk = 34

    // Pinned because build-tools 34.0.0 is corrupted in the local SDK install.
    // Not a considered choice — drop this line once the SDK is repaired.
    buildToolsVersion = "36.1.0"

    defaultConfig {
        applicationId = "io.dressup"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0-slice"
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"))
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
    }

    sourceSets {
        getByName("main").java.srcDirs("src/main/kotlin")
        getByName("test").java.srcDirs("src/test/kotlin")
    }

    // Item PNGs are already downsampled and optimised by build_catalog.py;
    // re-compressing them at package time only costs build seconds.
    androidResources {
        noCompress += "png"
    }
}

dependencies {
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.foundation)
    implementation(libs.compose.material3)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.kotlinx.serialization.json)

    debugImplementation(libs.compose.ui.tooling)
    implementation(libs.compose.ui.tooling.preview)

    testImplementation(libs.kotlin.test)
    testImplementation(libs.kotlin.test.junit)
}

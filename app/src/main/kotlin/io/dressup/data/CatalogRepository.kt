package io.dressup.data

import android.content.Context
import android.graphics.BitmapFactory
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import io.dressup.domain.CatalogItem
import io.dressup.domain.Character
import io.dressup.domain.SnapPoint
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.io.IOException

/**
 * Reads the catalog, the character definitions, and item bitmaps out of assets.
 *
 * Everything here is produced by `tools/build_catalog.py`. The app is fully
 * offline, so assets are the only content source and a missing or malformed file
 * is a build error that shipped — surfaced loudly rather than silently swallowed.
 */
class CatalogRepository(private val context: Context) {

    private val json = Json { ignoreUnknownKeys = true }
    private val bitmaps = mutableMapOf<String, ImageBitmap>()

    suspend fun loadCatalog(): List<CatalogItem> = withContext(Dispatchers.IO) {
        val dto = json.decodeFromString<CatalogDto>(readAsset(CATALOG_FILE))
        dto.items.map { it.toDomain() }
    }

    suspend fun loadCharacters(): List<Character> = withContext(Dispatchers.IO) {
        val dto = json.decodeFromString<CharactersDto>(readAsset(CHARACTERS_FILE))
        if (dto.characters.isEmpty()) {
            throw IllegalStateException("$CHARACTERS_FILE contains no characters")
        }
        dto.characters.map { it.toDomain() }
    }

    /**
     * Decode an asset image, memoised.
     *
     * Items are re-drawn every frame while dragging, so decoding must happen once
     * up front. The catalog caps images at 512px, which keeps the whole working
     * set comfortably within budget on a 4 GB tablet.
     */
    suspend fun image(path: String): ImageBitmap = withContext(Dispatchers.IO) {
        bitmaps.getOrPut(path) {
            context.assets.open(path).use { stream ->
                BitmapFactory.decodeStream(stream)?.asImageBitmap()
                    ?: throw IOException("asset is not a decodable image: $path")
            }
        }
    }

    private fun readAsset(name: String): String =
        try {
            context.assets.open(name).bufferedReader().use { it.readText() }
        } catch (e: IOException) {
            throw IOException("missing asset '$name' — run tools/build_catalog.py", e)
        }

    private companion object {
        const val CATALOG_FILE = "catalog.json"
        const val CHARACTERS_FILE = "characters.json"
    }
}

// -- wire format ---------------------------------------------------------
// Kept separate from the domain types so a catalog schema change is a compile
// error in one place rather than a silent behaviour change across the app.

@Serializable
private data class CatalogDto(
    val version: Int,
    val items: List<CatalogItemDto> = emptyList(),
)

@Serializable
private data class CatalogItemDto(
    val id: String,
    val category: String,
    val group: String,
    val image: String,
    val width: Int,
    val height: Int,
    val quality: Float,
) {
    fun toDomain() = CatalogItem(id, category, group, image, width, height, quality)
}

@Serializable
private data class CharactersDto(val characters: List<CharacterDto> = emptyList())

@Serializable
private data class CharacterDto(
    val id: String,
    val name: String,
    @SerialName("base_image") val baseImage: String,
    @SerialName("snap_points") val snapPoints: List<SnapPointDto> = emptyList(),
) {
    fun toDomain() = Character(id, name, baseImage, snapPoints.map { it.toDomain() })
}

@Serializable
private data class SnapPointDto(
    val id: String,
    val category: String,
    val x: Float,
    val y: Float,
) {
    fun toDomain(): SnapPoint {
        require(x in 0f..1f && y in 0f..1f) {
            "snap point '$id' is outside the 0..1 range: ($x, $y)"
        }
        return SnapPoint(id, category, x, y)
    }
}

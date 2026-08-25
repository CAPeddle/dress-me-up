package io.dressup.domain

/**
 * An item the player can place on a character. Mirrors one entry in
 * `assets/catalog.json` — keep in sync with `dressup_pipeline/models.py`.
 */
data class CatalogItem(
    val id: String,
    val category: String,
    val group: String,
    val image: String,
    val width: Int,
    val height: Int,
    val quality: Float,
)

/**
 * A place on a character where an item of [category] belongs.
 *
 * [x] and [y] are normalized 0..1 against the character image, so the same
 * character definition works at any canvas size. They mark the *centre* of the
 * placed item, not its top-left.
 */
data class SnapPoint(
    val id: String,
    val category: String,
    val x: Float,
    val y: Float,
)

/** A base body plus the snap points hand-authored for it. */
data class Character(
    val id: String,
    val name: String,
    val baseImage: String,
    val snapPoints: List<SnapPoint>,
)

/**
 * An item currently on the character.
 *
 * [snappedTo] is the id of the snap point it locked onto, or null when the player
 * placed it freely. Retained so a re-layout can re-derive position from the snap
 * point rather than trusting stale coordinates.
 */
data class PlacedItem(
    val instanceId: Long,
    val item: CatalogItem,
    val x: Float,
    val y: Float,
    val snappedTo: String? = null,
)

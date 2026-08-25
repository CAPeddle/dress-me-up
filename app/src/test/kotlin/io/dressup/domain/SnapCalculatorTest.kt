package io.dressup.domain

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

class SnapCalculatorTest {

    private val hatPoint = SnapPoint(id = "head", category = "hat", x = 0.50f, y = 0.20f)
    private val shoesPoint = SnapPoint(id = "feet", category = "shoes", x = 0.50f, y = 0.90f)
    private val points = listOf(hatPoint, shoesPoint)

    @Test
    fun `snaps to a matching point within the radius`() {
        val placement = SnapCalculator.resolve(0.52f, 0.23f, category = "hat", snapPoints = points)

        assertEquals("head", placement.snappedTo)
        assertEquals(hatPoint.x, placement.x)
        assertEquals(hatPoint.y, placement.y)
    }

    @Test
    fun `free-places when the nearest matching point is out of range`() {
        val placement = SnapCalculator.resolve(0.50f, 0.55f, category = "hat", snapPoints = points)

        assertNull(placement.snappedTo)
        assertEquals(0.50f, placement.x)
        assertEquals(0.55f, placement.y)
    }

    @Test
    fun `ignores snap points of a different category`() {
        // Dropped right on the shoes point, but carrying a hat.
        val placement = SnapCalculator.resolve(0.50f, 0.90f, category = "hat", snapPoints = points)

        assertNull(placement.snappedTo)
        assertEquals(0.90f, placement.y)
    }

    @Test
    fun `picks the nearest when several points share a category`() {
        val left = SnapPoint(id = "hand-left", category = "weapon", x = 0.25f, y = 0.55f)
        val right = SnapPoint(id = "hand-right", category = "weapon", x = 0.75f, y = 0.55f)

        val placement = SnapCalculator.resolve(0.70f, 0.55f, "weapon", listOf(left, right))

        assertEquals("hand-right", placement.snappedTo)
    }

    @Test
    fun `free-places when the character has no point for that category`() {
        val placement = SnapCalculator.resolve(0.50f, 0.20f, category = "wings", snapPoints = points)

        assertNull(placement.snappedTo)
    }

    @Test
    fun `free-places when the character has no snap points at all`() {
        val placement = SnapCalculator.resolve(0.5f, 0.5f, category = "hat", snapPoints = emptyList())

        assertNull(placement.snappedTo)
    }

    @Test
    fun `a drop exactly on the radius still snaps`() {
        val placement = SnapCalculator.resolve(
            dropX = hatPoint.x,
            dropY = hatPoint.y + SnapCalculator.DEFAULT_SNAP_RADIUS,
            category = "hat",
            snapPoints = points,
        )

        assertTrue(placement.isSnapped)
    }

    @Test
    fun `a wide canvas shrinks horizontal reach so the pull stays circular`() {
        // 0.10 to the right of the hat point. On a square canvas that is inside
        // the 0.12 radius; on a 2:1 canvas it is 0.20 of a screen-height away.
        val dropX = hatPoint.x + 0.10f

        val square = SnapCalculator.resolve(dropX, hatPoint.y, "hat", points, aspect = 1f)
        val wide = SnapCalculator.resolve(dropX, hatPoint.y, "hat", points, aspect = 2f)

        assertTrue(square.isSnapped)
        assertTrue(!wide.isSnapped)
    }

    @Test
    fun `a zero radius never snaps except on an exact hit`() {
        val exact = SnapCalculator.resolve(hatPoint.x, hatPoint.y, "hat", points, radius = 0f)
        val near = SnapCalculator.resolve(hatPoint.x + 0.01f, hatPoint.y, "hat", points, radius = 0f)

        assertTrue(exact.isSnapped)
        assertTrue(!near.isSnapped)
    }

    @Test
    fun `rejects a negative radius`() {
        assertFailsWith<IllegalArgumentException> {
            SnapCalculator.resolve(0.5f, 0.5f, "hat", points, radius = -0.1f)
        }
    }

    @Test
    fun `rejects a non-positive aspect`() {
        assertFailsWith<IllegalArgumentException> {
            SnapCalculator.resolve(0.5f, 0.5f, "hat", points, aspect = 0f)
        }
    }
}

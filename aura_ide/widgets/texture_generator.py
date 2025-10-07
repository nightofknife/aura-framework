"""
提供用于程序化生成背景纹理的工具。

该模块包含一个 `TextureManager` 类，它在程序启动时一次性生成
所有主题所需的背景纹理，并将它们作为 `QPixmap` 对象持有，以供
UI随时高效地使用。此外，它还提供了生成不同风格纹理（如噪点、波纹）
的底层函数。
"""
import numpy as np
from PIL import Image
from PySide6.QtGui import QPixmap, QImage
from noise import pnoise2


def pillow_to_qpixmap(img: Image.Image) -> QPixmap:
    """
    将 Pillow (PIL) 图像对象转换为 PySide6 的 QPixmap 对象。

    Args:
        img (Image.Image): 输入的 Pillow 图像。

    Returns:
        QPixmap: 转换后的 QPixmap 对象。
    """
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    qimage = QImage(img.tobytes("raw", "RGBA"), img.width, img.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimage)


class TextureManager:
    """
    在程序启动时生成并持有所有UI主题所需的 QPixmap 纹理。

    这个类作为一次性的纹理生成器和缓存器，确保在整个应用程序的生命周期中，
    背景纹理只需生成一次，之后可以被高效地重复使用。

    Attributes:
        dark_texture_pixmap (QPixmap): 暗色主题的背景纹理。
        light_texture_pixmap (QPixmap): 亮色主题的背景纹理。
    """

    def __init__(self, size: int = 256):
        """
        初始化 TextureManager，并生成所有主题的纹理。

        Args:
            size (int): 生成的纹理贴图的边长（像素）。默认为 256。
        """
        print("TextureManager: 正在生成程序化纹理作为 QPixmap...")

        dark_wave_img = generate_wave_texture(
            size=size,
            base_color=(26, 27, 30),
            wave_intensity=25,
            scale=150,
            octaves=5
        )
        self.dark_texture_pixmap = pillow_to_qpixmap(dark_wave_img)

        light_noise_img = generate_noise_texture(
            size=size,
            base_color=(247, 247, 247),
            noise_intensity=10
        )
        self.light_texture_pixmap = pillow_to_qpixmap(light_noise_img)

        print("TextureManager: QPixmap 纹理已生成。")

def generate_noise_texture(size: int, base_color: tuple, noise_intensity: int) -> Image.Image:
    """
    生成随机噪点纹理，通常用于模拟画布或纸张质感（用于亮色主题）。

    Args:
        size (int): 纹理的尺寸（正方形）。
        base_color (tuple): RGB 基础色, 例如 (247, 247, 247)。
        noise_intensity (int): 噪点的强度 (0-255)，建议值为 10-20。

    Returns:
        Image.Image: 一个 Pillow 图像对象。
    """
    img_array = np.full((size, size, 3), base_color, dtype=np.uint8)
    noise = np.random.randint(
        -noise_intensity,
        noise_intensity + 1,
        (size, size, 3)
    )
    img_array = np.clip(img_array + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(img_array, 'RGB')


def generate_wave_texture(size: int, base_color: tuple, wave_intensity: int, scale: float, octaves: int) -> Image.Image:
    """
    使用 Perlin 噪声生成平滑的、可平铺的波纹纹理（用于暗色主题）。

    Args:
        size (int): 纹理的尺寸。
        base_color (tuple): RGB 基础色, 例如 (26, 27, 30)。
        wave_intensity (int): 波纹的明暗强度 (0-255)，建议值为 15-25。
        scale (float): 噪声的缩放级别，值越大波纹越舒展。
        octaves (int): 噪声的细节层次，值越高细节越丰富。

    Returns:
        Image.Image: 一个 Pillow 图像对象。
    """
    img_array = np.zeros((size, size), dtype=np.float32)

    for y in range(size):
        for x in range(size):
            img_array[y][x] = pnoise2(
                x / scale,
                y / scale,
                octaves=octaves,
                persistence=0.5,
                lacunarity=2.0,
                repeatx=size,
                repeaty=size,
                base=np.random.randint(0, 100)
            )

    scaled_noise = (img_array * wave_intensity).astype(np.int16)
    base_array = np.full((size, size, 3), base_color, dtype=np.int16)
    final_array = np.clip(base_array + scaled_noise[:, :, np.newaxis], 0, 255).astype(np.uint8)
    return Image.fromarray(final_array, 'RGB')




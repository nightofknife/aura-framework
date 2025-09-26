# aura_ide/widgets/texture_generator.py (新建文件)

import base64
import io
import math

import numpy as np
from PIL import Image
from PySide6.QtGui import QPixmap, QImage
from noise import pnoise2


def pillow_to_qpixmap(img: Image.Image) -> QPixmap:
    """将Pillow图像对象转换为QPixmap"""
    # 确保图像是RGBA格式，以便QImage正确处理
    if img.mode != "RGBA":
        img = img.convert("RGBA")

    # 将Pillow图像数据转换为QImage
    qimage = QImage(img.tobytes("raw", "RGBA"), img.width, img.height, QImage.Format.Format_RGBA8888)

    # 从QImage创建QPixmap
    return QPixmap.fromImage(qimage)


class TextureManager:
    """在程序启动时生成并持有QPixmap纹理"""

    def __init__(self, size=256):
        print("TextureManager: Generating procedural textures as QPixmaps...")

        # --- 暗色主题: "黑曜石流" ---
        dark_wave_img = generate_wave_texture(
            size=size,
            base_color=(26, 27, 30),
            wave_intensity=25,
            scale=150,
            octaves=5
        )
        # 【修改】直接转换为QPixmap
        self.dark_texture_pixmap = pillow_to_qpixmap(dark_wave_img)

        # --- 亮色主题: "亚麻画布" ---
        light_noise_img = generate_noise_texture(
            size=size,
            base_color=(247, 247, 247),
            noise_intensity=10
        )
        # 【修改】直接转换为QPixmap
        self.light_texture_pixmap = pillow_to_qpixmap(light_noise_img)

        print("TextureManager: QPixmap textures generated.")

def generate_noise_texture(size: int, base_color: tuple, noise_intensity: int) -> Image.Image:
    """
    生成随机噪点纹理 (用于亮色主题)
    :param size: 纹理尺寸 (正方形)
    :param base_color: RGB基础色, e.g., (247, 247, 247)
    :param noise_intensity: 噪点强度 (0-255), 建议值 10-20
    """
    # 创建一个纯色背景
    img_array = np.full((size, size, 3), base_color, dtype=np.uint8)

    # 生成随机噪点
    noise = np.random.randint(
        -noise_intensity,
        noise_intensity + 1,
        (size, size, 3)
    )

    # 将噪点添加到背景上，并确保颜色值在0-255范围内
    img_array = np.clip(img_array + noise, 0, 255).astype(np.uint8)

    return Image.fromarray(img_array, 'RGB')


def generate_wave_texture(size: int, base_color: tuple, wave_intensity: int, scale: float, octaves: int) -> Image.Image:
    """
    生成平滑的Perlin噪声波纹 (用于暗色主题)
    :param size: 纹理尺寸
    :param base_color: RGB基础色, e.g., (26, 27, 30)
    :param wave_intensity: 波纹明暗强度 (0-255), 建议值 15-25
    :param scale: 噪声缩放, 值越大波纹越大, e.g., 100.0
    :param octaves: 噪声细节层次, 建议值 4-6
    """
    img_array = np.zeros((size, size), dtype=np.float32)

    # 生成Perlin噪声
    for y in range(size):
        for x in range(size):
            img_array[y][x] = pnoise2(
                x / scale,
                y / scale,
                octaves=octaves,
                persistence=0.5,
                lacunarity=2.0,
                repeatx=size,  # 保证水平方向无缝平铺
                repeaty=size,  # 保证垂直方向无缝平铺
                base=np.random.randint(0, 100)  # 随机种子，保证每次启动不一样
            )

    # 将噪声值从[-1, 1]映射到[-intensity, +intensity]
    scaled_noise = (img_array * wave_intensity).astype(np.int16)

    # 创建基础色数组并添加噪声
    base_array = np.full((size, size, 3), base_color, dtype=np.int16)
    final_array = np.clip(base_array + scaled_noise[:, :, np.newaxis], 0, 255).astype(np.uint8)

    return Image.fromarray(final_array, 'RGB')




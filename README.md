# Look Kit

A small Blender add-on that speeds up the repetitive parts of getting a character render to look finished: ink outlines, a lighting rig, a render preset and a simple color grade. It works for single images and for animations.

> Add a screenshot or a before/after image here (use work you made yourself).

## Features

- **Ink outlines** on selected meshes. Works in EEVEE and Cycles, stays stable in animation, and keeps lights and shadows working on the character. Line thickness and color are adjustable, and you can paint a vertex group named `LK_Line` to make lines thinner in chosen areas (weight 1 = full thickness, 0 = thin).
- **Freestyle outline option** as an alternative that never touches meshes or materials (render-time only).
- **Light rig:** warm key, cool fill, teal rim and warm kicker lights placed around the selected characters relative to the active camera, plus a button to dim the environment lighting.
- **Render preset** for Cycles or EEVEE: sampling, denoising, color management and 16-bit PNG output.
- **Compositor grade:** soft glow, edge color fringe and a teal-shadow / warm-highlight color balance.

## Requirements

- Blender 4.2 or newer. Developed and tested on Blender 5.2 (Windows). Other versions may need small fixes, so please report problems.

## Install

1. Download `look_kit.py`. The file must be named exactly `look_kit.py` (no extra numbers or dots in the name).
2. In Blender: **Edit > Preferences > Add-ons > Install from Disk**, choose the file, and enable **Look Kit**.

No install option: open the **Scripting** workspace, click **Open**, choose `look_kit.py`, and click **Run Script**. You will need to do this again each time you restart Blender.

## Use

1. Pose your characters and set the active camera.
2. Press **N** in the 3D viewport and open the **Look Kit** tab.
3. Select the character meshes (not the environment, and usually not eyes or eyelashes).
4. Click **Add Outlines to Selected**, then **Build Light Rig for Selected** and **Dim World Lighting**.
5. Choose Cycles or EEVEE and click **Apply Render Preset**, then **Set Up Compositor Grade**.
6. Render with **F12**. For animation, render a PNG sequence and encode it afterwards.

Clicking a button again updates the previous result instead of stacking a new one.

## Tips

- Line thickness is in world units, so it looks thicker in close-ups. Try about `0.002` for close-ups and `0.004` for full-body shots.
- If a model turns dark when outlines are added, use the Freestyle option instead and open an issue with the model type and Blender version.
- Select only the meshes you want outlined. Selecting eyes or transparent meshes can give black or odd results.

## Known limitations

- The compositor settings changed a lot in Blender 5.x. If a glow or color balance node cannot be configured, the add-on skips it and tells you which one.
- Lights are placed once relative to the characters' starting position and do not follow them if they move a long way.
- Freestyle lines only appear in final renders, not in the viewport.

## Credits

Created by **Voxelust**, with code and technical assistance from **[Claude](https://www.anthropic.com/claude)** (an AI assistant made by Anthropic). The idea, art direction, testing in Blender and publishing were done by the creator. See [CREDITS.md](CREDITS.md) for details.

## License

GPL-3.0-or-later. See `LICENSE`.

## Contributing

Bug reports and pull requests are welcome. When reporting a problem, include your Blender version, the render engine, and the message shown at the bottom of Blender or in the system console.

"""Default task for the supervised pill-transfer workflow."""

DEFAULT_PROMPT = (
    'Transfer the pills from the source cup into the empty cup. Approach from above and '
    'gently grasp the source cup near its rim without crushing its walls or blocking its '
    'opening. Leave the receiving cup on the table. Use all three camera views together. When '
    'the top camera cannot see the cup because an arm or gripper obscures it, use the '
    'wrist-camera views to assess the grasp, cup opening, remaining pills, and alignment with '
    'the receiving cup. Do not treat top-camera occlusion alone as task failure; pause if the '
    "necessary details are unclear in every view. Position the source cup's pouring edge over "
    "the receiving cup's opening. Slowly increase the tilt while maintaining alignment and a "
    'stable grasp. If pills remain, continue toward an almost upside-down orientation while '
    'keeping the pouring opening above the receiving cup and avoiding collisions. If pills '
    'are trapped by the gripper or a folded rim, stop rather than forcing rotation. Once '
    'transfer is complete, return the source cup upright, set it on the table, and release '
    'only when supported.'
)

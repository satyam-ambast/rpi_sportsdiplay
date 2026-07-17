from PIL import Image,ImageDraw
from services.pixel_font import blit_text, text_width, GLYPH_H


def create_scorecard_image(
    team1="IND",
    team2="AUS",
    score="245/6",
    overs="40.2",
    inns=1,
    target=0,
    lead=0,
    trail=0,
    day=1,
    filename="scorecard.png",
    bat_team='IND',
    bowl_team='AUS',
    match_type='L',
    size=32,
    state='Live',
    bg_color=(0, 0, 0),
    teams_color=(255, 255, 255),
    score_color=(255, 196, 0),
    overs_color=(120, 200, 255),
    inns_color=(100,255,120),
    line_color=(50, 50, 50),
    bat_colour=(0, 32, 96),
    bowl_color=(255, 110, 20),
):
    """
    Renders a 32x32 cricket scorecard badge.
    """
    if len(team1)>3:
        team1=team1[0:3]

    if len(team2)>3:
        team2=team2[0:3]

    if bat_team!=None and len(bat_team)>3:
        bat_team=bat_team[0:3]
    if bowl_team!=None and len(bowl_team)>3:
        bowl_team=bowl_team[0:3]





    img = Image.new("RGB", (size, size), bg_color)
    draw = ImageDraw.Draw(img)

    teams_line = f"{team1.upper()}  V  {team2.upper()}"
    overs_line = f"{overs} ({inns})"

    if match_type == 'ODI' or match_type=='T20':
        if inns > 1:
            innings_line = f"T : {target}"
        else:
            innings_line = f"I : {inns}"
    else:
        overs_line = f"{overs}  D{day}  "  
        score+= f" ({inns})"      
        if inns > 1 and lead > 0:

            innings_line = f"LEAD : {lead}"
            #overs_line = f"{overs}  D{day}"
            #overs_line = f"{overs} ({inns})"

        elif inns > 1 and trail > 0:
            innings_line = f"TRAIL : {trail}"

            #overs_line = f"{overs} ({inns})"
        else:
            innings_line = f"Day  {day}"
    
    if state.lower()=='lunch' or state.lower()=='tea' and state.lower()=='stumps' or state.lower()=='stumps':
        print("tea or lunch")
        overs_line+=state[0]

    rows = [
        (teams_line, teams_color),
        (score, score_color),
        (overs_line, overs_color),
        (innings_line, inns_color),
    ]

    row_h = GLYPH_H
    gap = 3
    total_h = row_h * len(rows) + gap * (len(rows) - 1)
    start_y = (size - total_h) // 2

    y = start_y

    # -----------------------------
    # Draw separator line
    # -----------------------------

    # Horizontal line between score and overs
    line_y = 7
    draw.line(
        [(0, line_y), (size - 1, line_y)],
        fill=line_color,
        width=1,
    )

    if bat_team==team1:
        draw.line([(0, line_y), (size//2 - 1, line_y)],fill=bat_colour,width=1,)
        draw.line([(size//2, line_y), (size - 1, line_y)],fill=bowl_color,width=1,)
    else:
        draw.line([(0, line_y), (size//2 - 1, line_y)],fill=bat_colour,width=1,)
        draw.line([(size//2, line_y), (size - 1, line_y)],fill=bowl_color,width=1,)

    # -----------------------------
    # Draw text
    # -----------------------------
    y = start_y
    for text, color in rows:
        w = text_width(text, spacing=1)
        x = max(0, (size - w) // 2)
        blit_text(img, x, y, text, color, spacing=1)
        y += row_h + gap

    img.save(filename, "PNG")
    return img

def create_batting_scorecard_image(striker,non_striker,
    size=32,
    bg_color=(0, 0, 0),
    name1_color=(255, 196, 0),
    score_color=(120, 200, 255),
    name2_color=(100,255,120),
    line_color=(50, 50, 50),
    filename="batters.png",):
    
    img = Image.new("RGB", (size, size), bg_color)
    draw = ImageDraw.Draw(img)

    batter_1_list=striker['name'].split(" ")
    batter_1_line=batter_1_list[0][0]+".  "+batter_1_list[-1][:3]
    score_1_line=f"{striker['runs']} ({striker['balls']})"

    batter_2_list=non_striker['name'].split(" ")
    batter_2_line=batter_2_list[0][0]+".  "+batter_2_list[-1][:3]
    score_2_line=f"{non_striker['runs']} ({non_striker['balls']})"

    rows = [
        (batter_1_line, name1_color),
        (score_1_line, score_color),
        (batter_2_line, name2_color),
        (score_2_line, score_color),
    ]


    row_h = GLYPH_H
    gap = 3
    total_h = row_h * len(rows) + gap * (len(rows) - 1)
    start_y = (size - total_h) // 2

    y = start_y

    # -----------------------------
    # Draw separator line
    # -----------------------------

    # Horizontal line between score and overs
    line_y = size//2-1
    draw.line(
        [(0, line_y), (size - 1, line_y)],
        fill=line_color,
        width=1,
    )

    # -----------------------------
    # Draw text
    # -----------------------------
    y = start_y
    for text, color in rows:
        w = text_width(text, spacing=1)
        x = max(0, (size - w) // 2)
        blit_text(img, x, y, text, color, spacing=1)
        y += row_h + gap

    img.save(filename, "PNG")
    return img


def create_bowling_scorecard_image(bowler1,bowler2,
    size=32,
    bg_color=(0, 0, 0),
    name1_color=(255, 196, 0),
    score_color=(120, 200, 255),
    name2_color=(100,255,120),
    line_color=(50, 50, 50),
    filename="bowlers.png",):
    
    img = Image.new("RGB", (size, size), bg_color)
    draw = ImageDraw.Draw(img)

    bowler_1_list=bowler1['name'].split(" ")
    bowler_1_line=bowler_1_list[0][0]+".  "+bowler_1_list[-1][:3]
    score_1_line=f"{bowler1['overs']}-{bowler1['runs']}-{bowler1['wickets']}"

    bowler_2_list=bowler2['name'].split(" ")
    bowler_2_line=bowler_2_list[0][0]+".  "+bowler_2_list[-1][:3]
    score_2_line=f"{bowler2['overs']}-{bowler2['runs']}-{bowler2['wickets']}"

    rows = [
        (bowler_1_line, name1_color),
        (score_1_line, score_color),
        (bowler_2_line, name2_color),
        (score_2_line, score_color),
    ]


    row_h = GLYPH_H
    gap = 3
    total_h = row_h * len(rows) + gap * (len(rows) - 1)
    start_y = (size - total_h) // 2

    y = start_y

    # -----------------------------
    # Draw separator line
    # -----------------------------

    # Horizontal line between score and overs
    line_y = size//2-1
    draw.line(
        [(0, line_y), (size - 1, line_y)],
        fill=line_color,
        width=1,
    )

    # -----------------------------
    # Draw text
    # -----------------------------
    y = start_y
    for text, color in rows:
        w = text_width(text, spacing=1)
        x = max(0, (size - w) // 2)
        blit_text(img, x, y, text, color, spacing=1)
        y += row_h + gap

    img.save(filename, "PNG")
    return img




if __name__ == "__main__":
    create_scorecard_image(
        team1="IND", team2="AUS",
        score="360/2", overs="40.2", inns=3, lead=41, match_type='T',bat_team='IND',bowl_team='AUS',
        filename="scorecard.png",
    )
    create_batting_scorecard_image(striker={"name": "Nat Sciver-Brunt","runs": 39,
    "balls": 74,
    "fours": 3,
    "sixes": 1,
    "strike_rate": 52.7},
    non_striker={
    "name": "Mady Villiers",
    "runs": 5,
    "balls": 7,
    "fours": 0,
    "sixes": 0,
    "strike_rate": 71.43})

    # upscaled nearest-neighbor preview, for eyeballing crispness/legibility
    img = Image.open("bowlers.png")
    img.resize((32 * 12, 32 * 12), Image.NEAREST).save("bowlers_preview.png")

from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle

INK="#1f2933"; MUTE="#5f6b7a"
C1="#d9e6f2"; C2="#fbe3b8"; C3="#cfe8dc"   # regimes
ACC="#b4540a"

fig,ax=plt.subplots(figsize=(13,6.2),dpi=200)
ax.set_xlim(2017.7,2031.9); ax.set_ylim(0,10.7); ax.axis("off")

# regime bands
bands=[(2018.0,2021.5,C1,"USD-fixed price\n13.3 US c/kWh, 10 years\n(Law 5346, Annex I)"),
       (2021.5,2023.33,C2,"YEKDEM in TL\nquarterly indexation\n(Decision 3453)"),
       (2023.33,2031.0,C3,"YEKDEM in TL\nmonthly formula, USD floor/ceiling\n(Decision 7189, plants commissioned until 31 Dec 2030)")]
for x0,x1,c,t in bands:
    ax.add_patch(Rectangle((x0,5.2),x1-x0,2.6,fc=c,ec="white",lw=2))
    ax.text((x0+x1)/2,6.5,t,ha="center",va="center",fontsize=9.5,color=INK,linespacing=1.4)
ax.text(2018.0,8.0,"Support price regime",fontsize=10,color=MUTE,fontweight="bold")
# 10-year rule note
ax.plot([2021.5,2021.5,2031,2031],[7.95,8.1,8.1,7.95],color=MUTE,lw=1.2)
ax.text(2026.25,8.35,"10-year rule: support lasts 10 years from commissioning. After that the plant sells at PTF\n"
        "(unlicensed surplus: min(0.9 × YEKDEM, PTF)). The first plants of this regime reach year 10 in mid-2031.",
        ha="center",va="bottom",fontsize=9.5,color=INK,linespacing=1.45)

# axis arrow
ay=4.1
ax.plot([2018,2026.87],[ay,ay],color=INK,lw=2.2,solid_capstyle="butt")
ax.plot([2026.87,2031.3],[ay,ay],color=INK,lw=2.2,ls=(0,(4,3)))
ax.add_patch(FancyArrowPatch((2031.2,ay),(2031.75,ay),arrowstyle="-|>",mutation_scale=18,color=INK,lw=2.2))
for y in range(2018,2032):
    ax.plot([y,y],[ay-0.09,ay+0.09],color=INK,lw=1.2)
    ax.text(y,ay+0.3,str(y),ha="center",va="bottom",fontsize=9.5,color=INK if y<=2026 else MUTE)

# data points
pts=[(2018.0,"2018","7.9 TWh","2.6%"),(2021.0,"2021","13.6 TWh","4.1%"),
     (2024.0,"2024","26.7 TWh","7.8%"),(2026.87,"Nov 2026","38.9 TWh*","12.2%")]
for x,lab,t,s in pts:
    ax.plot([x,x],[ay,3.45],color=ACC,lw=1.2)
    ax.text(x,3.2,lab,ha="center",va="center",fontsize=9.5,color=MUTE)
    ax.plot(x,ay,"o",ms=9,mfc=ACC,mec="white",mew=2,zorder=5)
    ax.text(x,2.6,f"{t}",ha="center",va="center",fontsize=13,fontweight="bold",color=INK)
    ax.text(x,2.0,f"{s} of generation",ha="center",va="center",fontsize=9.5,color=INK)
# 2030 projection
ax.plot([2030,2030],[ay,3.45],color=ACC,lw=1.2,ls=(0,(3,3)))
ax.text(2030,3.2,"2030",ha="center",va="center",fontsize=9.5,color=MUTE)
ax.plot(2030,ay,"o",ms=9,mfc="white",mec=ACC,mew=2,zorder=5)
ax.text(2030,2.6,"52 TWh - 12%",ha="center",va="center",fontsize=13,fontweight="bold",color=ACC)
ax.text(2030,2.0,"Ember projection",ha="center",va="center",fontsize=9,color=MUTE)

ax.text(2018.0,10.15,"Turkey's solar generation and support prices, 2018–2030",fontsize=15,fontweight="bold",color=INK)
ax.text(2018.0,9.6,"Solar = licensed + unlicensed (incl. self-consumption surplus)",fontsize=10,color=MUTE)

ax.text(2018.0,0.55,"TWh = yearly production; % = share in total generation. *2026: January to mid-November, not a full year.\n"
 "Source: EPİAŞ (EXIST)",
 fontsize=8.5,color=MUTE,va="center",linespacing=1.5)
OUT = Path(__file__).resolve().parent.parent / "blog" / "2026-11-solar-market" / "images" / "solar_timeline.png"
plt.savefig(OUT,bbox_inches="tight",facecolor="white")

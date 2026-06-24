# GoS Hackathon — 23 June 2026

- **Recording:** https://fathom.video/share/_dSxjrzt7bNdGsxZhH5ycNE4-uSuK8xS (67 mins)
- **Attendees:** Benjamin Schwarz (ctoic.net / GoS), Dom (Norsk), Simon, IAMT (Stan), Marisol Palmero
- **Saved:** 2026-06-24 — verbatim Fathom transcript, kept for reference (the `/prepare-rem`
  spec and the unified-uploads work both derive from it).

## Key outcomes / actions
- No hackathon ran today (prep slipped); **next hackathon set for Wed 8 July, 4pm**.
  Objective: **device-side upscale energy** (SDR→HDR and HD→4K), with **constant-quality
  codec comparison** as the second priority. Cloud (REM) measurement chosen; local 2s as a
  separate variance check.
- **Pixop is now a full GoS member.**
- HEVC→H.264 rollback is topical (Disney HEVC-patent suit) → refresh codec energy data;
  OWL (server) + REM (device) are well placed. Also feeds the IEEE primary-data framework.
- **Prepare REM files** (Ben→Simon): new OWL page to encode a chosen source to a target
  VMAF (default 92) and wrap it in timer + black/white/black markers for REM playback
  experiments. Segment = `1-min timer · 30s black · 30s white · 30s black · ~6.5-min video
  · ~1-min black tail` ≈ 10 min. Constant audio; markers delimit REM's analysis window.
  Simon to supply the timer-generation shell script + (ideally) a pristine-4K marker mezzanine.
- **Jan Ozer report idea (Dom):** give Jan a hosted, low-setup workflow — upload a couple of
  videos, run a constrained scenario, get a consistent 2–3 page draft report with watt /
  watt-hour numbers he can turn into an article. (This file is the source for that discussion.)
- New OWL bits demoed: VMAF on every run + past results carry near-live data; "reproduce this"
  bundle; sports content (Kranjska downhill MTB) added; ML enhancement (/enhance-run) with
  CompressedVQA-HDR no-reference scoring; the basement-move "cooler GPU costs ~10% more energy"
  finding (NVIDIA auto-boost clock when cool → power wasted while waiting).
- Hardware leads: Monsoon Solutions 200 ms-resolution power monitor (battery-replacement for
  phones, Python-controllable) via InterDigital; G&L (Alexander) offered to send NetInt ASIC
  cards (cleaner provenance than NetInt direct).

---

## Transcript

0:00 - Benjamin Schwarz (ctoic.net)
  Hi, is my camera on? Yes, I'm on. Your camera's on. Everything's on. I meant my mic, sorry. I can see my camera's on.

0:11 - IAMT
  It's okay. Did you have a good time in India? Well, I wasn't in India.

0:17 - Benjamin Schwarz (ctoic.net)
  Oh, sorry.

0:19 - IAMT
  I was doing a Lower Danube cruise.

0:22 - Benjamin Schwarz (ctoic.net)
  Oh, right, in Europe, sorry. I knew you were traveling. But that's okay.

0:26 - IAMT
  Anyway, I'm back online. I was back and then right into Infocom.

0:31 - Benjamin Schwarz (ctoic.net)
  So, and trust me, it wasn't a great place.

0:38 - IAMT
  It was 46 degrees in Vegas.

0:41 - Benjamin Schwarz (ctoic.net)
  Wow. Well, it's 40.

0:43 - IAMT
  And you guys are suffering from heat, too, right? Yeah, it's really bad here. Not quite that much.

0:51 - Benjamin Schwarz (ctoic.net)
  or five days, the weather forecast say, well, tomorrow is the worst day, then it's getting better. And it's been like that for like four days now.  Right. And so we should have Simon any minute, he's certainly coming. And Marisol said she'd come, so we'll give it a minute or two.  Oh, yeah, I have a great thing I want to share with you guys. don't know how much it'll cost, but this will be really cool.  Oh, battery mobiles. Yeah, so just what picks up means for our, and from there we have Simon, let's talk about next, yeah, the next hackathon.  Hacks and TVs. So yeah, Dom, I gather I got something wrong in the dates for the World Cup, you said.  Sorry about that. did it very carefully. It must have been a cut-and-paste error. I will fix it.

2:39 - Dom (Norsk)
  Yeah, not being anything of a football person, I just went and looked at the dates, and it was like Saturday, I think you had like Saturday the 19th, and it was like Sunday the 19th.

2:51 - Benjamin Schwarz (ctoic.net)
  Okay. It was all out of sync, so I thought the best thing to do is if you send out invites directly, that's probably going to make sure I'm...  Okay. I did it carefully, was in a table, and then I think the cut and paste must have...

3:05 - IAMT
  Anyway, since I've been away, just give me an update.

3:08 - Benjamin Schwarz (ctoic.net)
  Yeah, so we're measuring... On what you're up to, yeah. Okay, yeah, so we'll do that. Let's open this meeting.  It was going to be a hackathon, but both Simon and I dropped the ball a bit last week and sort of woke up on Sunday saying, oops, hackathon Tuesday, we haven't got ready for it, so we're not doing a hackathon today.  We've got quite a few interesting things to talk about to prepare the next one. So Simon has some ideas that he's going to talk about with the Apple TV and the HDR mode there.  There's some stuff to do. I have some things that I want to share with you guys. I'm looking for...  So I'll tell you what I want to talk about, things I need for Rem and OWL and how they need to integrate.  Um... Got some exciting news from, yeah, the Pixop is now fully a member, so what that changes, what we can do with new things we can test, thanks to them.  And we need to discuss the next hackathon, but I'll let Simon drive that discussion, which is linked to the previous one.  And, yeah, I have a bunch of points I want to raise, but who has other topics? We were going to have a short presentation by TNO, but I don't think we're going to have it now.  I've got some bad news this morning from them, is they haven't secured budget to renew. So we've been through this cycle with them once before, they said that six months ago, and they did renew for six months, so we'll see what happens.  I'm not sure they're aware that the rates are much lower now, so perhaps we still might get them, but that was a bit of a disappointment this morning.  By the way, Marisol, they said that that had nothing to do with the discussions they're having with you concerning the IEEE.  So, yeah, and some news which isn't WattLab related, but just so that, as I've got only board members here, I might as well talk about it, this doing some exciting work with Marisol, we're going to have a big board decision to make whether we can move forward or not.  Let me see, Marisol, if I can remember the simple way of expressing it. We are proposing to the IEEE, are looking for this kind of thing, it's not unsolicited.  We are proposing a framework methodology that would enable people to create primary data in their reporting around videos. So, typically what that means is that the regulations in Europe have just changed, the CSRD has loosened in many respects, but it's got a little bit tighter in one small respect, is that they distinguish primary and secondary data.  And the... Before, you could do as much secondary data as you want. Secondary data is just what Dom calls, I can't remember the expression, but basically finger in the air data.  As long as you say where it comes from, you can use it. Now they're saying you need to have a certain amount of primary data, which is either measured by you or from a secured source.  And so we could provide some of that primary data in the world of streaming. So typically that would mean I'm an operator, I'm moving from H.264 to H.265, therefore I am claiming.  that I will be reducing my data load by 20% or something. And that would be secondary data if they were saying it.  But if they were saying it through various experimentations, through OWL and REM and stuff, it could become primary data.  But it's a big, it's a long shot. I mean, if it works, it'll be operational in between one and two years.  So it's a broad decision as to whether we, how much energy we put into that. So, so I just wanted to put you up to date with that.

7:00 - Dom (Norsk)
  Worth throwing into the pot on that, I don't know if you saw, I'd have to dig a post out, I'm doing this from memory, but somebody just sued Disney over HEVC use because of the HEVC patent, I think it was in sight, think.  Like, somebody sued Disney anyway, and one of their three paths forward is to just pull back from HEVC, which would have a massive energy impact on if all of Disney's content goes back from HEVC to H.264, then there would be potentially quite a significant energy impact, certainly on client devices.

7:47 - Benjamin Schwarz (ctoic.net)
  Actually, that's really interesting, because what that might mean, Marisol, I still have to work on the document you sent me, but we could also position this as something we're going to work on anyway, which would make it a lot more...  A much easier decision for the board and say, we're working in this direction anyway, we've got this potential project with IEEE, either directly or through Huawei, and if the project with IEEE works, great, and even if it doesn't work, we can still produce some of this work because it's so topical.  So I love that contribution, that stirring the pot is really useful, Dom.

8:26 - simon
  Yeah, that's interesting.

8:27 - Dom (Norsk)
  I found a link, put it in the chat room, there you go.

8:30 - simon
  Yeah, I think it's an area that we need to refresh data on, because it's a while back that we actually did the ABC and HEVC comparison, and that was one of the areas I wanted to discuss for a future hackathon.

8:48 - Benjamin Schwarz (ctoic.net)
  Okay, well that would be really cool, because Owl has still got, the paint is still wet on Owl, but that is Owl's strong point.  Owl is totally focused on something like comparing HEVC. We see HEC64 at the server side, and if we can do with REM at the client side, then we'll be in a perfect position.  Yeah. That's really reassuring.

9:12 - Dom (Norsk)
  The second link I just shared, actually, as Jan hosts this breakdown on it, which specifically says, turn off HECC and pull back to HEC64.  Yeah. That would have quite an impact on any energy.

9:27 - Benjamin Schwarz (ctoic.net)
  Well, here's something. This could be the first real use of OWL, at least at the server side. I could set up some scripts to do some in-depth comparison.  Because one of the new things that's not fully on the UI yet, but I'm working on, because I picked up at, which is kind of a dull moment I picked up in Berlin last week, is that operators will often have a VMath constraint.  You know, all the transcoding farms and stuff, they say our constraint is 92 VMath minimum. see now. is Just  That's what RTL told me. And so I built that into bits of it, but I can build it into more bits of it because, Dom, I built your page for you, energy constraint.  I have 100 kilowatts or 100 megawatts or whatever. What can I do with it? And I already put the VMAF score there.  So I said, this is my energy and this is my quality. But what I could do is run a series of tests saying, well, moving back down from H.265 to H.264, oh, this is the implications for quality, bitrate, and energy.  And I can do it at the server side. And then with Simon, we'd need to set up the next hackathon could produce fresh data at the client side, because that's part of the data we lost from H&R's data loss, right?

10:46 - simon
  That's it. If you can store and share those encoded files, so if they're encoded in forms, it can easily be just streamed out, you know, pushing it from FFmpeg to.

11:00 - Benjamin Schwarz (ctoic.net)
  Then we can do the comparison of that.

11:03 - simon
  The one piece that we didn't do before was producing content items that were very comparable, mean opinion scores of quality.  You know, we did bitrate, we did resolution, but quality was a dimension we didn't explore.

11:19 - Benjamin Schwarz (ctoic.net)
  Tell me, Sammy, do you use Claude at all? Yes, I was having a bit of a debate with him earlier today to do what I wanted him to Because if you use Claude even quicker, because if you log in to, with SSH, into the server, you go to the WhatLab directory, so you just go to your home and go to WhatLab from the home, and there's the Claude.md, and if you fire up a Claude session there, you can ask it anything, you'll get instant answers to where you can say, give me a script to RCP, all the files from here to here, it kind of knows everything.  It can answer instantaneously, without even checking where things are. And stuff, because it's all in the documentation of the thing.  So you just need to log in, use your SSH to log in, and you can get any of it.  If you don't have time, tell me and I can just send you the paths. They're all on the server.  Okay, sorry for that interlude. Let's get back to business to drive this WhatLab call about things. One quick question.  I don't know if you can help, Stan. I need to find a way to get a TV that, when it's switched on, it goes straight to watch a stream.  Does anybody know of a way of doing that? Because if I could find such a TV that somehow would point to something we're doing immediately, it would just be so amazing what we could do with OWL.  I could connect it to OWL, and OWL could turn it on, and it would be a wonder machine for  I just don't know where to start, thinking about how to get a TV to behave like that.

13:05 - IAMT
  So I have a little IR box that's connected into Wi-Fi and it turns the TV on with Alexa and it runs my news channel and it moves over channels and does whatever.  And what it does here is every morning, you know, I've changed things now, but you recall I always had an IABM circular thing going on.  It turned my TV on every morning and it moved over to the USB input and it ran that file.  It was an automated stream that I put in. That's how Windows Media 17 used to work.

13:52 - Dom (Norsk)
  Yeah, I used to work for a company on the front of the box.

13:56 - IAMT
  Yeah, so it's a little IR box. I picked up ages ago. I'll see if I can find out.

14:06 - Benjamin Schwarz (ctoic.net)
  Let me just tell you what makes it. The I mean, yeah, the advantage with the infrared solution is to be relatively simple to set up.  The big disadvantage, I've been down that path many, many years ago, is that it works wonderfully when it works.  And then some minor little thing changes in the order in which you have to press page up, page down, channel, up arrow.

14:26 - IAMT
  Oh, yeah, yeah, absolutely. I had to put in all sorts of delays. Well, if there was a programmatic way, that would be safer.

14:35 - Benjamin Schwarz (ctoic.net)
  If there was a way of waking a TV up on the network and saying, hey, TV, do this.

14:44 - simon
  I think all new TVs bring you up to the manufacturer UI.

14:50 - Benjamin Schwarz (ctoic.net)
  Isn't there a TV that you could set to go to the last input? So a TV, when you turn it on, it goes to the last input, and then we do everything.

15:02 - simon
  I think my LG, when I turn it on, goes to the HDMI which is powered up with it, which is my Apple TV, so that is another route, but then you've got to drive the Apple TV to do what you want, and that's, you know, you're just moving the problem up along the chain.  Yeah, it wouldn't be, yeah, Apple TV is maybe hard to program, but then I'm thinking the device could be a media server of some kind, I mean, based on a Raspberry Pi, or...

15:30 - Dom (Norsk)
  Just basing stuff I've Googled into the chat room, there you go.

15:34 - IAMT
  Well, I'm surprised that your TV doesn't do that, that it doesn't go up to the last input when you turn it on.  It just, it just goes to the, to the OEM crop on the screen to say, do you want to watch this, this, or whatever.

15:57 - Benjamin Schwarz (ctoic.net)
  But, I just clicked on the link and it... So your audio is cracking up, I didn't catch it, I'm sorry, I've got a fan that blows up my mic, let me just point it in a different direction, it doesn't cool me down then, but now your audio is back.  Okay, so, okay, let's not solve the problem here, but what we're saying is there are solutions. Let me show you another thing that I was quite excited to, so I met the guys from InterDigital, and I'm quite keen to really work hard at getting them to join now, because they've changed, they've upgraded their PVR technology, which would fit wonderfully into OWL.  And they showed me something that got me really excited, and should get you excited too, Simon, is this little website, an American company called Monsoon Solutions.
  SCREEN SHARING: Ben started screen sharing — WATCH: https://fathom.video/share/_dSxjrzt7bNdGsxZhH5ycNE4-uSuK8xS?timestamp=1030.03182  And so they sell this box here. I don't know the price, it's a few grand, it's not very expensive.  It's basically a power supply that also acts as a 200 millisecond resolution power monitor. And so it can power things, and they have a service, you tell them what phone you want, they buy the phone, they remove the battery, and they install this instead.  And so you can basically run any kind of mobile device through them. And that, again, I believe there's Python scripts to control everything, and this also could be attached to OWL.  And so we'd get some, we could, again, live stream something. Thing to a mobile device and get the live energy in a really reliable way, unlike all the software probes that we've looked at.  So I don't know if you were aware of this either, Marisol, if anybody in Telefonica and Huawei Group have used these solutions.  But this is what InterDigital is using. So I was really excited. mean, unfortunately, we don't have loads of spare cash because, like, you know, they cost a few grand each time.  But exciting. It's the first time I've actually come across a live working solution. So I just discovered it this morning.  Obviously need more time. But really excited. Before we talk about the other... The other... What we're going to do in the next...  Um, hackathon, uh, just want to show you, so, um, I'm still waiting for your feedback, Dom, now that your page, this should be the Dom page, is live, it's working on real data, um, and, um, this is what you said, you know, what can I do with a certain energy, so, you know, you can put any number you want in there, and it updates immediately below, and it says, okay, for 10,000 watt hours, if you're aiming for 92, uh, by default, it's 92 VMAF, but you can push that up if you want, you say, no, I'm a 94 VMAF company, um, it gives you what you can do with the different CPU, with the different, uh, codecs, hardware and software, of course, and if, if it's all too big, you can get rid of that and say, just, so we can compare H.264 with H.265, just for the debate we were having with Disney and all that, uh, and you can see  You can really see the difference there, you know, for the same energy budget. It's not huge, the difference there, but you can make it change by changing things like the PMF.  And then the other thing I wanted to tell you guys, too, is that Alexander from, I met Alexander from G&L.  He's the CEO of G&L, who's one of our dormant companies, member companies, but hopefully will become active again, because I met him for breakfast and told him about my presentation, and he actually showed up.  He came into the room just before my presentation, for my presentation. And afterward, he was really, really impressed and said, I love what you're doing.  Let me send you some ASIC cards. And so I'm really happy about that because I didn't really want to get the ASIC cards off NetInt, because if NetInt send them to us, it'll be much harder if we have anything negative to say about them.  Whereas this way, we'll get the NetInt cards through G&L. He's a great player.

21:00 - Dom (Norsk)
  That I think is what, so I don't know if that relates to that third link I sent on the chat, which is he's obviously setting up to do a load of measurement in his facility, and he's got some Zigbee smart plugs, might be worth making sure he uses OWL if he can.

21:18 - Benjamin Schwarz (ctoic.net)
  Okay, I'll do that, and the other thing I want to say, so this is the brand new, this is the DOM page, just so you know how it's structured, basically this is an offshoot of the main video page.  So this is the main video page that hopefully some of you have seen already, where you can compare the three main codecs, software versus hardware, or both.  Then there's some comparison ladders, there's a compare all, so that's like a five or six minute run for a two minute clip, or like a 25 minute run if you take full clips.  What also is new is, I put a teeny little file there too, by default, so if you want to do a quick test and you don't have time, we can do one now while I'm talking.  So let's say I want to compare, I just want the eight. H2645 comparison on this Goss promo. While it's doing it, I can upload and, oops, I didn't select it.  That's interesting. Select the file, idiot. This one, there we go. Run measurement. So there you are, it's doing the stuff.  While it's doing it, let me just talk you through some other novelties here. So everything it does now, it includes VMAF scoring at the end.  And when it's HDR, we use another kind of scoring. I'll show you. And so it's running the test right now.  Does it allow you to delete the file? Delete which file? The test file.

22:47 - Dom (Norsk)
  So if I upload a file, can I then subsequently delete it?

22:50 - Benjamin Schwarz (ctoic.net)
  So in this version, it deletes, it's a circular buffer. So it will delete itself. You can't manually delete it.  It's really Easy to implement if you think that's...

23:01 - Dom (Norsk)
  Well, I would think if you send it to David Ronka and to Jan Ozer, they will start... Because Jan is constantly reviewing codec performance and he would go to town on this.  But if he's got... If David Ronka, for example, has samples of... I can't remember where he was, whether it was Facebook or Disney Le well, last, and Ben Wagner as well, they might well have a play, but their content might be something that they would need to immediately remove got it okay well that that that thing ran so i'll note for for fathom if you i've got the cheap fathom now so i don't know if this will work but action for ben is just to include a remove remove file as soon as processing is finished option for uploading and note for ben to also follow up with janosa in particular once he's got it going and maybe ben wagner and david ronka they're the voices you want to get behind it if you get them if you get them

24:05 - Benjamin Schwarz (ctoic.net)
  And so the big novelty here is that I've included the VMAF scores of the two different files. And so you can't yet target a certain VMAF on this thing, but I can easily build that.  But it's a bit more complicated. But at least they're being fully reported. And there's another slight improvement is when you look at past results now, They're actually, you can actually get almost all the data that you got live.  So that's quite cool. And you can still download everything. You've got this Reproduce This button, which gives you access to the, so this gives you access to the source.  When you tick Reproduce This, it doesn't give you, so let me just remind myself what happens. So I need to, I need to share my whole screen then to show you what's going on.
  SCREEN SHARING: Ben started screen sharing — WATCH: https://fathom.video/share/_dSxjrzt7bNdGsxZhH5ycNE4-uSuK8xS?timestamp=1500.580482  Let me just stop sharing there and share again. So I just clicked on that and reproduced this. I did this like over a month ago, time goes so fast, I forgot exactly how it works.  So there's a README markdown file, the Python script to do the comparison, and if I'm not mistaken, it should have the link to, come on, ah, I can't get the top of it.  So this is the markdown file. So this is what we measured. If you want to run it again, ah, does it actually have the link to the data?  Ah, no, you have to have the file here. But what I can do is I can, ah, I can change this to create a link to the data, to, to the, to, to, to the actual file that was used.  Um, and then it has the expected output. So, um, yeah, so, so just, I wanted to show you how this was structured.  So this is our main page, and what I showed you... The DOM page is transcode options for set energy budget is an offshoot of the main page.  And then, while I have your attention, I just want to show you the other thing. So this is the brand new stuff, the machine learning based video enhancement.  So I've left an underdevelopment GOSS only sign for short term. That will be removed when I get the green light from multiple people.  But this lets you upload any file you want. But here there's a slight difference as it says, yeah, you click on keep on GOSS after run.  So if you don't click there, it will be deleted. So I've developed it here, but I didn't put it on the main thing.  So that's what I need to make the same everywhere. And here you've got a whole bunch of things. You've got Big Buck Bunny and multiple resolutions.  They've all been prepared as clean, dirty, 4K, HD. We've got the reference, 4K, all these different files. You can choose any.  And then what you can do is you can convert to HDR, you can convert to HD, you can down-convert to SD, you can up-convert to 4K, you can run all of these different things, run and measure, and you see the results.  And then you've got an option, Servers Live, which is really cool because what that means is, I could just show you how that works, I'll just do one.  So let's take a, I don't know, the worst case, Big Buck Bunny in standard definition that's dirty, it's been, the encode's been damaged a bit on purpose, that's the file we're using, and I can do, convert to HDR, and if I, so that's got Servers Live, so what that means is that when it runs, it's running now, there's a normalization first, anything that's not standard, it normalizes the file before running, then it waits for idle.  Flex the baseline, and then it's running the transcode, and you'll see these transcodes really draw power, sometimes goes up to 400 watts.  And here we've got video players involved, so you can look at the source and the output. I'll let that run.  What I wanted to show you was something else, let me open another page so I don't waste your time here.  This is REM. Let me go to another page with OWL. While that's working, you can see it's really driving the thing.  And I wanted to show you, yeah, a sub-page of this, which is the sweet spot ladder. So the run that's happening right now, I did over an eight-hour period.  I ran it on standard definition input. HD input, 4K input, clean and dirty. And so you can see here we've plotted the quality gain versus the energy input, the energy used.  And you can see that when you send, here is the reference file. So you send the pristine 4K and you try and improve it with, you use a lot of power and you have absolutely zero improvement.  It was already pristine 4K. Then, obviously, the best possible use of your energy budget with upscale machine learning is, you can look at the video itself, it's a bad quality UGC that I shot in 2005 on a pre-iPhone phone, you know, so it was, that's because of that file that I had to build a normalization because FFmpeg wouldn't even recognize the file, so everything's normalized.

29:55 - IAMT
  It was probably 15 frames a second, was it?

29:58 - Benjamin Schwarz (ctoic.net)
  How did you know that? How

30:00 - IAMT
  Yeah, yeah, well. It was exactly 15 frames a second, and it was, and it dropped frames too.

30:08 - Benjamin Schwarz (ctoic.net)
  It had quite a lot of dropped frames in the 15 frames per second. But that, when you run that through, it only costs almost nothing energy-wise, and, you know, you get a two-point uptick there.  And, you know, this is the, what I'm running right now, we'll go back to the results. This is Big Buck Bunny in standard definition, a dirty file.  It only costs 15 watt-hours to uplift that. So just go back to that. should be finished by now. Oh, no, it's still transcoding.  Sorry, guys, it was longer than I thought. Oh, because I'm doing HDR.

30:45 - IAMT
  So what you're showing was the decoding took more energy than the uplift.

30:52 - Benjamin Schwarz (ctoic.net)
  So, I just wanted the WattLab crew to be aware of this technology. Now have on OWL so we can use it as part of our thinking process and it's going to be, this is why, Simon, I very much hope we can either run in the next hackathon or soon after to plan a hackathon dedicated to upscale on the device, both, so you're already working on one of them which is the SDR to HDR, so the question how much does it cost to go from SDR to HDR on the device, and then how much does it cost to go from HD to 4K on the device?  Those are the two questions, if we can address that, then we'll have a really interesting story to tell about, okay, you're an operator, you're getting a certain feed, it's got quality issues, what's the best way to address that from an energy perspective?  So now it's probing the file, this unfortunately takes a little bit of time because this is the file, this  We're working, in this particular case, I do have the original reference, but because it works on non-reference, we're using a completely different technique to VMAF.  It's called Compressed VQA HDR. It's a brand new project from 2025. I did a lot of research, and it does seem to be these are the guys doing the best quality measurement without a reference.  And so what you can see, before I go anywhere else, is, yeah, the quality of the source was 5.5, and the quality of the output is 7.7.  And I don't know what screens you guys are using right now. Let me just quickly show you. If you have a decent screen, you'll see what I mean.  Just before anything, I don't know if you've got an HDR monitor. I've got an HDR monitor. This is the source.  This is the output. I mean, there's a huge difference just there. And then if you watch it in full screen with a little bit of video, and we've even got audio now.  Look, I don't know whether... So you can see it, but it is absolutely horrible that, for me at least, on the machine, that's the input, and if I look at the output, it's much cleaner.  I don't know if you can see that. Colors are completely different, it's cleaner, and this is the illustration where machine learning enhancement does wonders to really bad content.  It's not that useful when the content's already quite good.

33:30 - IAMT
  That makes sense. Of course, Zoom is blowing out some of the highlights.

33:35 - Benjamin Schwarz (ctoic.net)
  Yeah, it's not perfect.

33:37 - simon
  Even on Zoom, it's definitely better.

33:40 - IAMT
  It is better, yeah.

33:41 - Benjamin Schwarz (ctoic.net)
  And here you've got all the energy. So I ran it as a live, but it fell behind, okay? Yeah.  that was too much for it. We only have one graphics card. I'd need two graphics cards to do that in real-time.  Because it says that, basically, it ran at 0.26 real-time. But when it can, it runs at 1x, but it still calculates the mean.  So it says to do this kind of work, if we had two graphics cards, would cost about 300 watts.  You have an awful, really bad source to make it pristine, costs about 300 watts with this technology.

34:16 - Dom (Norsk)
  So, Ben, just a few questions about OWL as it's coming together. mean, you're running off some great experiments here.  Are you running a local language model now?

34:30 - Benjamin Schwarz (ctoic.net)
  Yes, I've got loads of people, but I'm not using the language model. mean, basically, I've been focused on these.

34:37 - Dom (Norsk)
  Okay, hold on, hold on, hold hold on, hold If you're running a local language model, it might be worth trying to create some sort of automated report output, because this is a great tool.  Someone like Jan Ozer should be using this. But it's going to take a while for Jan to be able to collate.  The data from various experiments interpret it and turn it into a report, whereas if you actually could go through a cycle of giving him a login, letting him try some content through it, through different scenarios, and then also generating a draft report, which he could turn into an article, then it'll shorten the cycle from him playing with it and running videos into producing articles.  And so I would think, you know, I'm looking at this, and I would honestly think that you should be getting Jan on this as soon as possible, but I think he will get confused by, you know, overwhelming amount of things that you can test and do.  Whereas if you can say, just put a couple of videos in here, and test them, and we're going to give you a summary three-page report, which he can then write an article from, and have a consistent.  That would be great, because this is kind of like giving someone an amateur, and what I'm proposing is you actually give them a workflow to create reports, which is what he needs to share.

36:12 - Benjamin Schwarz (ctoic.net)
  But then I'd need a little bit of guidance as to what the report is about, because this can either compare codecs, it can compare content, and it would be a different setup.

36:23 - Dom (Norsk)
  You know, if we're trying to find information out about the codecs, or trying to find information about content, or, but he's a codecs guy, he cares about codecs guy, he cares about quality versus CPU at the moment, or quality versus, you know, how densely you can encode is typically his sort of space.  But if you can now go add to that, that set of reporting, given this scenario, we did this, this, this set of encodings on our system that we looked at it from an energy perspective, he can also sit there and go, ran all these reports.  On the latest setup of this particular configuration of FFmpeg or whatever it is, and when I ran it on the greeningofstreaming.org system, it's reporting that H.264 is 3 watts per hour more efficient than HEVC or whatever.  You want to sort of really simplify that for him to be able to go, oh, on my test bench, I'm going to generate the content, and then I'm going to push the two bits of content to OWL and get a watt number back.

37:34 - Benjamin Schwarz (ctoic.net)
  Well, what I could have is another, so there's sort of three big entry points right now. A guided tour just takes you through all the functionality, the video transcode we've been through, the machine language enhancement.  There could be a completely different kind of button here is create your own report or something. And then you go into there, you'd upload the video, and you just have very, very few things to select.  And... And... And you'd run it, and it would, yeah, that's something I could definitely do, but, and then say, on this piece of content, this is what we found out.

38:08 - Dom (Norsk)
  I'd have a look at a couple of his reports, and what he writes about, and work at how you can add watts, or watt-hours, to his reports throughout, because the sooner you can do that, then I'll pick up with Jan and get us a meeting.  He's a good friend, and I'm sure he'd take it really seriously, especially if it's hosted, and he doesn't have a lot to set up, but just has to upload some stuff and hit go.  Then he's got a reference, a reference system, and will, I'm sure, consistently report what we're doing. I would have thought there's quite a lot of people like that who would quite like to use that.  It's like a benchmarking tool. Sounds good.

38:45 - Benjamin Schwarz (ctoic.net)
  Oh, and by the way, guys, there's, in the findings page, which you can now find from the, yeah, from the homepage, this one, I really need, there's so much to do, guys.  I don't want to overload you, so let's not do it now, but we need a session on some of these findings.  These are findings which can be published, and they're done in a way when you click on them, they're really, they're supposedly, know, they've got a copy button.  Oh, exactly, exactly this. This is more or less exactly what I was thinking of it, yeah. But this is, so these are ones I generate from time to time using Claude.  But this one was  amazing to me, and what happened was I moved the OWL server from under my desk to my basement, which is about 10 degrees lower, because, because the current heat wave.  And what happened was that the energy cost went up by 10%. It was 10 degrees lower, everything became 10% more expensive on the GPU, not on the CPU.  And lots of investigations, I'm pretty sure the finding is correct now, I really... We pushed it and did some research.  What simplistically said, the NVIDIA GPU, when you say, OK, I want you to do this piece of work, if you don't explicitly set all the parameters like its clock speed, it says, OK, I'm just about to do this piece of work.  What's my headroom? Oh, right, I'm currently very cool, so I'm going to put a really high clock speed. And then what happens is, as the GPU draws all the power, because of the fact we don't have unified memory and stuff like that, the GPU is actually spending quite a lot of time waiting.  And when it's waiting on a very high clock cycle, that consumes a lot of energy. And a lot of energy.  So I ran a whole, found the knee curve, where the energy, so now I force the GPU clock to a set thing that I've tested, and I have to re-run that test whenever we change the environment.  And I thought that was really amazing. So, transcoding costs 10% more in a...

41:02 - Dom (Norsk)
  It's a really mad, mad result.

41:04 - Benjamin Schwarz (ctoic.net)
  But you should be blogging this stuff quickly. Yeah, will be.

41:08 - IAMT
  I'm still confused by that, still on that side, your conclusion on that. You sure your fans weren't against the wall or anything like that?

41:20 - Benjamin Schwarz (ctoic.net)
  Yeah, yeah, it's in a clean space, and I've run a whole bunch of things. So there's a whole lot of hidden pages, by the way, and anybody who wants them.  So, for example, we've got a page called Audience. Yeah, that works. That shows everything in a number of pages that have been viewed.  So really cool. Now, 64 different member sessions have happened. I don't use member sessions. I'm Lab or LAN. That's me, 4,000 sessions.  But these are all non-sessions by me, 1,700 anonymous public sessions. And, you know. They're the main pages that we use, so there's pages like that.  Let me, yeah, so let's get back to this meeting to wrap it up because we want to talk about the next hackathon.  So I said what I needed, I'll look into those battery things. I'll look into the, trying to get a TV to be automatic so that way we can link part of our with part of REM.  That would be really exciting. And so, Simon, next hackathon, we need to set a date and an objective. Yeah, just before that, so the World Cup, I'll send an email out tomorrow with invites for, I'll just send, it's everybody in, everybody who's going to be doing the recording is either in WhatLab or it's, we've got one, not one, non-WhatLab person is Andrew Ladbrook.  So I'll send WhatLab plus Andrew Ladbrook the invites to the matches to make sure everybody does them.

42:57 - simon
  Yeah, and I'll share out the device. That I'm going to use, I've got it reset up, so I can run some tests.

43:07 - Benjamin Schwarz (ctoic.net)
  Great, so quickly let's select a date for a hackathon, and this time try and not forget until the day before, so we can prepare it.  Let's start with the date and then work backwards. So I think what with the summer coming has to be before July the 14th, because that's kind of, so, or July the, I'm a way, that week.  I could do the 17th of July, but is that too late?

43:40 - simon
  I can do the afternoon, but no, I can do the 17th, that's okay, but that's, what, three weeks, isn't it?

43:47 - Benjamin Schwarz (ctoic.net)
  Yeah, otherwise I could do the morning, well, yeah, it would have to be the morning or early afternoon of the 10th, or we could do as early as the 8th.  Eighth is good for me, tenth is no given.

44:03 - simon
  Okay, both of those work for me, so an extra person's always welcome, Dom.

44:09 - Benjamin Schwarz (ctoic.net)
  So if do 4 p.m., can you do 4 p.m. on the 8th, Stan?

44:14 - IAMT
  What day of the week is that?

44:15 - Benjamin Schwarz (ctoic.net)
  Sorry, that's Wednesday the 8th.

44:18 - IAMT
  Yeah, that works, yeah.

44:20 - Marisol Palmero
  We can do that day as well.

44:22 - Benjamin Schwarz (ctoic.net)
  Great, so we have a date. You can just put a note in there what we're going to be doing, Benzie, if we need Yeah, yeah, I'll put it in the, I'll update so that we're just going to determine that.  So we've got upscale if we, will we be ready to do, to test the upscale, Simon, do you think?

44:42 - simon
  I think the choice is either upscale or quality. Upscale is probably easier because I think there's less work in creating the content.  So we can probably work as we did before. I can get those streams. I would really think, from an interest perspective, if we can create a number of content items that are to the same quality but different codecs, I think that would be very interesting, I don't think we've really looked at that.  So I think let's Let's de-risk by trying to prioritise scaling first and constant quality second.

45:38 - Benjamin Schwarz (ctoic.net)
  What do you mean by constant quality?

45:41 - simon
  Well, comparing codecs that generate the same quality content. So the same mean opinion score. Because you've been looking at the total energy to create a content item.

45:58 - Benjamin Schwarz (ctoic.net)
  Yep. And encode a content item.

46:00 - simon
  And you can look at that and compare across codecs. It'd be great to do that comparison across decoders on devices.  And to make it, I think, to make it a meaningful comparison, if we take the same piece of content, same resolution, obviously, but produce an output file that has this very, very close mean opinion score, then we would see whether...

46:31 - Benjamin Schwarz (ctoic.net)
  Well, I could do that with Owl. If you give me the specs, because one thing Owl did recently is I push all content to 4.0.0, sorry, because Pixop content, they're used to working in uplink, you know, in contribution fees.  So they were 4.0.2, which meant that it couldn't be displayed on a TV and... So I spoke to them and did my research and said, well, it doesn't actually make any difference from an energy perspective.

47:05 - simon
  But if you give me the specs of exactly what you want the sources to look like, I can create them out of, so my three contents.

47:13 - Benjamin Schwarz (ctoic.net)
  Oh, and I forgot to say one other important novelty, which I haven't even finished testing myself, is if you go to the main video page, I now have sports content.  So I did some research, so there's a downhill bicycle ride, and so you can test that content too. So I have that, so I have currently available that content, Big Buck Bunny and Meridian.  I have them in two-minute extracts or the full thing. So Meridian is 12 minutes and Big Buck Bunny I think is 8 minutes or something like that, 10 minutes.  And the downhill is 6.4 minutes. If you tell me. What content you want. Not only can I produce them exactly in the format you want, I can also have all the energy of the production cost.

48:07 - simon
  Okay, that's good. And then we need to see how we take that and produce content that has the energy markers that allow us to pick that up from the playback.

48:22 - Benjamin Schwarz (ctoic.net)
  So the energy marker, do you have a small video file with the energy marker?

48:25 - simon
  They need, I think they need to be the same encoding parameters, same codec, same everything. So we might.

48:34 - Benjamin Schwarz (ctoic.net)
  So if I remember rightly, the energy marker is exclusively a FFmpeg output. It's just basically a bunch of commands to FFmpeg and it creates the file we need, right?  Oh, there was the white noise. We included white noise.

48:52 - simon
  I don't think white noise is not necessary for the marker. I think, yeah, if you, if you know, tell me.  If you select the content item that we're going to encode, look, do the analysis of its format, we can use FFmpeg to create a white segment and a black segment in that format, and then we can throw all of those at the same encode.

49:19 - Benjamin Schwarz (ctoic.net)
  But couldn't we do that with the timer? Just for running, it was just so cool having the timer when we run hackathons.  If we don't have a timer, it makes life harder.

49:29 - simon
  Can we create a timer with FFmpeg, or that was Yes, the timer is a separate video file. So, yeah, if you let me know, we'll do an exchange of information in terms of the formats that you need to align with the content item you're encoding, so that you can then just encode all the pieces, and we can then just concatenate those together, because we don't want to change codec or any other parameters.  This is wonderful.

50:03 - Benjamin Schwarz (ctoic.net)
  We're actually starting the REM OWL integration today. What I can do is I can quickly build you a page called REM prep or something, prepare REM files, and it will open a menu, which do you want of my pristine sources?  I have the three sources. You choose the source, and you choose the output. Just quickly tell me now in this meeting, the output will be what codec you want.  That's the choice, obviously. We have the three at the moment.

50:31 - simon
  Yes. Codec. Resolution. That is codec, resolution, and quality are the ones I'd like to do the test for. Yeah.

50:43 - Benjamin Schwarz (ctoic.net)
  And as I say, my understanding is 92 is the kind of magic, 92 VMAF. So by default, it'll aim for 92 VMAF.  And what we can do is I can have it so that you set the thing, and it will change.  But that will change the bit rate. mean, the easiest. way to reach the right quality is by changing the bitrate.  So is the bitrate fixed or not?

51:06 - simon
  I don't think the bitrate... No, think we've tried constant bitrate and see what the bitrate does. Let's try constant target, a common target quality, and adjust the simpler parameters to achieve that across the different codecs.  And I can generate the source files for that. The timer is easy. I've got a script that will just generate a timer.  We just then set the encoding parameters that we want for that. And then we create the elements and then run a concatenation process that just bolts through all things together.  Because if they're the same encoding parameters, then they will easily bolt together. We need to ensure that there is a constant audio across the wall as well.

51:59 - Benjamin Schwarz (ctoic.net)
  So just to... To show you what that implies in my understanding, this is going for a constant bitrate, so low complexity, meridian, this is the, so whether it's energy budget or file size will be the same.  When you go high complexity, instead of 35 hours, you only get 26 hours there, and with sports content, you're going to get loads of hours, but this is a 13 megabit stream, because my parameter here is constant vMath.  So if you have constant quality, then your bitrate shoots up, so that's 13 megabits compared to meridian's 3 megabits for the same code.  You're going from 3 megabits to 13.

52:43 - simon
  Yeah, this is very much, I agree, content variable, and therefore I think we might actually repeat this with three different content.  Sports content, which has a lot of motion, requires a lot of bits to represent that motion, entertainment quality, and some other.  Entertainment content or whatever. So I think that's another dimension, which means we want to make it as easy to run this process for getting the data back.  Now, the question is, to date, we've just looked at measuring the power, but if we want to do comparison, I think we just want to look at, well, what was the playback energy for this asset?  And therefore, I think we need to think about how accurately we can measure the energy with the cloud. If we're sampling very infrequently, I don't think we're going to get a very good measure or a repeatable measure of the energy consumed.  If we're measuring locally, and I note your problems that you saw across different TAPO versions of the speed that you can access and read the data.

53:54 - Benjamin Schwarz (ctoic.net)
  Worst case is 1.5 seconds.

53:56 - simon
  Yes, I think if we simplify on two. Then the question to Marisol and co is, can you run the Python script to measure this at a two-second interval locally, or are we limiting the participants by that?  Because I think that will mean a more accurate measurement of total energy.

54:27 - Benjamin Schwarz (ctoic.net)
  Just to clarify also that the upgrade I did to REM, to Dom's version that he handed over to me, is it now has this new focus mode, and I've done a lot of testing on that.  When you put focus mode on, where it will focus just on the devices in the current experiment, 10 seconds latency can be achieved 99.9% of the time with up to 12 devices.  So there's only five or six of us. So I'm just saying. I'm the option, if we don't do the local measurement, is we can now guarantee 10 seconds.

55:05 - simon
  Okay, that might be sufficient then, so maybe I'm worrying about a problem, but I do think that's another piece of work to do on completeness.

55:14 - Benjamin Schwarz (ctoic.net)
  It's a double problem, because we haven't, the local script, when you're running it off the LAN, you're collecting the data locally, which also means there's the issue of data collation.

55:28 - simon
  Yep.

55:29 - Benjamin Schwarz (ctoic.net)
  You know, which is a manual process, which is error-prone and stuff like that, the great thing about doing it with REM, it does mean that we will have less things to test, because each of your segments has to last 30 seconds, you know, the...

55:42 - Dom (Norsk)
  I'm sorry, I need to go, I'm just sorry to interrupt, just a quick one, but...

55:47 - IAMT
  I need to leave here, too.

55:49 - Benjamin Schwarz (ctoic.net)
  Okay, you'll all get instructions, yeah, whether we need local... I'll stay on the line a little bit longer with Simon to determine whether we need...

55:57 - simon
  Let's go for cloud. Let's a separate piece of work to see what the variability between if we measure on the cloud, then repeat the experiment measured locally, what is the variance in the result?

56:16 - Benjamin Schwarz (ctoic.net)
  And do you want to upload any of your data, your video files to OWL so we have consistency over what we've been measuring over the last three years?  Because Big Buck Bunny and Meridian are kind of new. I can happily, but there's the issue of you are okay with sharing it in a small group.  If it goes on to OWL, you know, it gets publicly viewed kind of thing.

56:41 - simon
  I think the piece that we use from Netflix, open source content, that should be fine. I think, to be honest, on that sailing content, it's kind of so historic that I don't think anyone will raise any concerns.  And, you know, I can always say that, you know, while I was... That BT, I allowed greeningofstreaming to use it, you know.

57:06 - Benjamin Schwarz (ctoic.net)
  But is it worthwhile, or because OWL has those three pieces of content?

57:12 - simon
  I don't know. It's very, I think it's the most valuable content we've got for HDR, SDR. For codec comparison, no, it doesn't matter.

57:26 - Benjamin Schwarz (ctoic.net)
  Yeah, it's not perfect content for codec comparison, because it's not consistent in either complexity or luminance or anything. It changes all the time.  No, that's it.

57:36 - simon
  And, you know, we used quite a bit of that Netflix stuff, I think, was shot in Mexico, that sequence.

57:46 - Benjamin Schwarz (ctoic.net)
  Well, I'm using Meridian, but that's, you didn't use Meridian, did you?

57:50 - simon
  I can't remember which one I, oh, no, Effluente or something I used. It wasn't Meridian, but yeah, we can use that.

57:58 - Benjamin Schwarz (ctoic.net)
  Okay, so. you.

57:59 - simon
  So.

57:59 - Benjamin Schwarz (ctoic.net)
  Thank So you don't really care what the content is, as long as it has the energy. So I've understood the black and the white.  That's easy. I can get OWL to produce that. But it's just how do I incorporate the timer?

58:13 - simon
  I can send you a timer file. I can build one. It's a script. And the content I just rebuilt to do my work on playing on the TV or playing on Apple TV to the TV, measuring two devices.  I want to do the total energy measurement piece. I just created a simpler piece of content because the stepping up in white and boxes isn't terribly relevant.  That's very interesting in terms of how the display works, how that maps to luminance. But in terms of total energy for a regular piece of content, it's not, I don't think it's terribly significant.  So I've got a script that will generate a timer. man. Of given duration into a given format. I'll upload these scripts.

59:07 - Benjamin Schwarz (ctoic.net)
  Another issue then is if we're going to measure one of the things we want to do with, we spoke about earlier with Jan Oso and stuff is to understand the difference with going back from HEVC to H.264, for example, then don't we need realistic content?  Because then the black and white markers will kind of spoil our encode energy measurement. I'm thinking out loud here in the sense that it's really simplistic stuff.  You know, a black screen for 30 seconds is not very complicated to encode. And then we go into regular video.  Won't that sort of water down the energy differences?

59:53 - simon
  No, because if we use the markers to delimit the segment... ... Of data that we're going to analyze, because if you're REM, you've got the polling intervals, you've got the player buffer fill intervals, you need that marker to say, this is where the video starts, and you need the marker then, this is where the video stops, and then you just cut those out and look at the data you've got for the video.

1:00:22 - Benjamin Schwarz (ctoic.net)
  For reading, for reading, yeah, but for the encoding part, if I generate them, oh, so what I need, I need to, I need to do something that Al doesn't know how to do yet, I have to build this, so that when it creates the marker part of the file, it doesn't start measuring energy yet, it then pauses, I don't know if I can pause mid, mid.

1:00:43 - simon
  I think that's, no, I think that's a complexity, I think with FFmpeg, you can concatenate segments of identical video, so you create the video part, and then it can  It doesn't need to normalize or anything like that, as long as you've encoded each of the elements you're concatenating together with the same parameters, and it's done on second boundaries, a group of picture sizes or intervals.

1:01:14 - Benjamin Schwarz (ctoic.net)
  The simplest thing would be if one of us could build the marker file with the timer in pristine 4K in some kind of mezzanine format, leave that sitting on owl, and when owl generates something, it just then normalizes it to whatever its current parameter is, its current thing, and creates it that way.

1:01:35 - simon
  Yeah. Well, I think the best thing is I can get that up and running, and then just move those scripts onto owl, and then it can just do it.

1:01:47 - Benjamin Schwarz (ctoic.net)
  Which leaves you another thought.

1:01:51 - simon
  One of the things that we had was the time was different lengths. Is it best to have the timer at the end of the sequence, and therefore we know that  When we're analyzing the data, the data we're analyzing starts on the hour or the 10 minute, and then the sequence, the time was at the end, or is it better to put the time in the middle?  Where do you feel subjectively that's better?

1:02:19 - Benjamin Schwarz (ctoic.net)
  The time.

1:02:20 - simon
  Yeah, because I think when we did it before with the cloud version and the LAN version, the timers were of different length.  I think I'm worrying about a non-problem, because the timer now, if we're doing this, the timer is a fixed length, everything can be 30 seconds, we don't need to worry about LAN or WAN measurement differences, you know, I worried about that before, because then I can get a final step.

1:02:50 - Benjamin Schwarz (ctoic.net)
  why don't we make it even simpler? It's black, white, black, right? Yeah. With timer throughout, or the timer. Timer just for the last segment.

1:03:02 - simon
  I think that...

1:03:04 - Benjamin Schwarz (ctoic.net)
  No. Black, white, black, then timer. Yeah? Or is the timer part of the black, white, black? No.

1:03:12 - simon
  The timer is where you would expect to make any changes.

1:03:20 - Benjamin Schwarz (ctoic.net)
  Okay, so the timer is the very beginning. So we start with a timer, 30-second timer, then 30 seconds of black, 30 seconds of white, 30 seconds of black, and then we start the video.  Yeah, okay.

1:03:32 - simon
  Well, what I've actually gone for is one-minute timer, 30 seconds of black, white, black, and also tail the video with a black.

1:03:43 - Benjamin Schwarz (ctoic.net)
  Yep.

1:03:44 - simon
  So you have seven minutes of video, two minutes of marker, and one-minute of timer. Okay. Yeah, I'll put the timer at the beginning because it makes it easier for people to understand.

1:03:59 - Benjamin Schwarz (ctoic.net)
  The work case is... My sports content is 6 minutes and 40 seconds, so we're just missing 20 seconds of content to make it to 7 minutes.  So 2 and a half minutes before, then 7 minutes of video and 30 seconds of black. Yeah, we could always make the last black a minute, if that's going to make it easier to work with your shortest piece of content.  And then each segment is 10 minutes.

1:04:28 - simon
  Yeah, which is very nice for an experiment.

1:04:32 - Benjamin Schwarz (ctoic.net)
  Okay, so I can produce those. It's just the 30-second timer. If you can send me the script for the 30-second timer, otherwise I can reinvent, just let's not reinvent the wheel.

1:04:44 - simon
  Okay, well good. I'll produce those, and I can create a page so that we can recreate them whenever we have new content.  So you'll select the content, and there'll be an option to upload if you want. Yeah.

1:04:54 - Benjamin Schwarz (ctoic.net)
  And then what I'll write the script to do is to target a certain VMaf. Which by default will be 92, but you can change.

1:05:02 - simon
  Yes.

1:05:03 - Benjamin Schwarz (ctoic.net)
  And then it will run its encode, it will check the VMAF. If the VMAF is off, it'll re-encode, playing with the bitrate until it gets the right VMAF.

1:05:13 - simon
  Okay.

1:05:13 - Benjamin Schwarz (ctoic.net)
  So sometimes you'll press run, and it'll take three minutes, sometimes it might take 20 minutes, you know, because it'll take some time to find the right VMAF, and I'll have it report what's going on.

1:05:24 - simon
  And then we can do it for three different codecs. And potentially we could do it against, you know, the different content segments you've got, like sport, because that, as you're saying, pushes up the bitrate, because it's the motion.  Yep.

1:05:43 - Benjamin Schwarz (ctoic.net)
  And so the bitrate will change, so Meridian will have a very low bitrate, Big Bug Bunny will have a medium bitrate, and the sport will have a huge bitrate.

1:05:52 - simon
  Yeah. Okay. And then we can drop those onto the TNO server, run a script. If MPEG just RTSPs out to the packager, and the packager, I'll create a couple more support.  I think I need to create a web page for each hackathon, in effect.

1:06:14 - Benjamin Schwarz (ctoic.net)
  Okay. So just send me the instructions or a Python script for the timer if you have it. Otherwise, I'll have to recreate something.  But as you've already created it, it'd be a shame to reinvent the wheel. So I've got to go because I've got a dry run for tomorrow's call.

1:06:34 - simon
  Okay. It's both shell scripts, calling FFMPEG. Okay. No problem.

1:06:40 - Benjamin Schwarz (ctoic.net)
  Cheers, Benjamin.

1:06:41 - simon
  Take care. Bye. Bye.

    // ===== 🎰 长按Logo抽奖大转盘 =====
    (function() {
        var trigger = document.getElementById('brandTrigger');
        if (!trigger) return;
        var longPressTimer = null;
        var isLongPress = false;
        var PRESS_DURATION = 600;

        trigger.addEventListener('mousedown', startPress);
        trigger.addEventListener('mouseup', endPress);
        trigger.addEventListener('mouseleave', cancelPress);
        trigger.addEventListener('touchstart', function(e) {
            startPress();
        }, {passive: true});
        trigger.addEventListener('touchend', function(e) {
            endPress();
        });
        trigger.addEventListener('touchcancel', cancelPress);

        function startPress() {
            isLongPress = false;
            longPressTimer = setTimeout(function() {
                isLongPress = true;
                // 视觉反馈
                trigger.style.transform = 'scale(0.95)';
                setTimeout(function() { trigger.style.transform = ''; }, 100);
                // 触发抽奖
                openLotteryWheel();
            }, PRESS_DURATION);
        }
        function endPress() {
            if (longPressTimer) {
                clearTimeout(longPressTimer);
                longPressTimer = null;
            }
        }
        function cancelPress() {
            if (longPressTimer) {
                clearTimeout(longPressTimer);
                longPressTimer = null;
            }
        }

        // ===== 打开转盘 =====
        function openLotteryWheel() {
            var overlay = document.createElement('div');
            overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;z-index:99998;background:rgba(0,0,0,0.7);backdrop-filter:blur(8px);display:flex;align-items:center;justify-content:center;animation:fadeIn 0.3s ease;';

            var modal = document.createElement('div');
            modal.style.cssText = 'background:linear-gradient(145deg,#1a1a2e,#16213e);border:1px solid rgba(255,215,0,0.2);border-radius:24px;padding:24px;max-width:420px;width:90%;box-shadow:0 0 60px rgba(255,215,0,0.1);position:relative;';

            // 标题
            var titleRow = document.createElement('div');
            titleRow.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;';
            titleRow.innerHTML = '<span style="font-size:20px;font-weight:800;color:#fff;letter-spacing:1px;">🎰 派工抽奖</span><span style="font-size:11px;color:rgba(255,255,255,0.3);cursor:pointer;" onclick="this.closest(\'div[style*=\\"z-index:99998\\"]\').remove()">✕ 关闭</span>';
            overlay.appendChild(modal);

            // 先用loading占位，异步获取人员数据
            modal.innerHTML = '';
            modal.appendChild(titleRow);

            var loadingDiv = document.createElement('div');
            loadingDiv.style.cssText = 'text-align:center;padding:40px 0;color:rgba(255,255,255,0.5);font-size:14px;';
            loadingDiv.textContent = '🔄 加载人员...';
            modal.appendChild(loadingDiv);

            document.body.appendChild(overlay);

            overlay.addEventListener('click', function(e) {
                if (e.target === overlay) overlay.remove();
            });

            // 请求人员数据
            var xhr = new XMLHttpRequest();
            // 读取当前选中的组
            var teamParam = '';
            var teamSelect = document.getElementById('dashTeamSelect');
            if (teamSelect && teamSelect.value) {
                teamParam = '?team=' + encodeURIComponent(teamSelect.value);
            } else {
                // 从 URL 读取 team 参数
                var urlParams = new URLSearchParams(window.location.search);
                var urlTeam = urlParams.get('team');
                if (urlTeam) teamParam = '?team=' + encodeURIComponent(urlTeam);
            }
            xhr.open('GET', '/data/persons/lottery-json' + teamParam, true);
            xhr.onload = function() {
                if (xhr.status === 200) {
                    try {
                        var resp = JSON.parse(xhr.responseText);
                        if (resp.persons && resp.persons.length > 0) {
                            buildWheel(modal, resp.persons, overlay);
                            return;
                        }
                    } catch(e) {}
                }
                loadingDiv.textContent = '❌ 加载失败，请重试';
                loadingDiv.style.cursor = 'pointer';
                loadingDiv.onclick = function() { overlay.remove(); };
            };
            xhr.onerror = function() {
                loadingDiv.textContent = '❌ 网络错误';
                loadingDiv.style.cursor = 'pointer';
                loadingDiv.onclick = function() { overlay.remove(); };
            };
            xhr.send();
        }

        // ===== 构建转盘 =====
        function buildWheel(modal, personsData, overlay) {
            modal.innerHTML = '';
            var titleRow = document.createElement('div');
            titleRow.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;';
            titleRow.innerHTML = '<span style="font-size:20px;font-weight:800;color:#fff;letter-spacing:1px;">🎰 派工抽奖</span><span style="font-size:11px;color:rgba(255,255,255,0.3);cursor:pointer;" onclick="this.closest(\'[style*=\\"z-index:99998\\"]\').remove()">✕ 关闭</span>';
            modal.appendChild(titleRow);

            var persons = personsData.slice();
            var n = persons.length;
            var funColors = ['#FF6B6B','#FECA57','#48DBFB','#FF9FF3','#54A0FF','#5F27CD','#01A3A4','#F368E0','#EE5A24','#0ABDE3','#10AC84','#5D62E5','#A29BFE','#FD79A8','#6C5CE7','#00CEC9','#E17055','#0984E3'];
            persons.forEach(function(p, i) { p.color = funColors[i % funColors.length]; });
            var angleStep = 360 / n;

            // 转盘容器（保证正方形）
            var wheelWrap = document.createElement('div');
            wheelWrap.style.cssText = 'position:relative;width:300px;height:300px;margin:0 auto 16px;';

            // 指针
            var pointer = document.createElement('div');
            pointer.textContent = '👇';
            pointer.style.cssText = 'position:absolute;top:-12px;left:50%;transform:translateX(-50%);z-index:10;font-size:36px;filter:drop-shadow(0 3px 6px rgba(0,0,0,0.4));';

            // 转盘
            var wheel = document.createElement('div');
            var stops = [];
            for (var i = 0; i < n; i++) {
                var st = i * angleStep;
                var en = (i + 1) * angleStep;
                stops.push(persons[i].color + ' ' + st + 'deg ' + en + 'deg');
            }
            wheel.style.cssText = 'width:300px;height:300px;border-radius:50%;background:conic-gradient(' + stops.join(',') + ');position:relative;box-shadow:0 0 0 6px rgba(255,255,255,0.1),0 0 0 10px rgba(0,0,0,0.3),0 0 40px rgba(251,191,36,0.2);';

            // 名字标签
            for (var i = 0; i < n; i++) {
                var aD = i * angleStep + angleStep / 2;
                var rd = (aD - 90) * Math.PI / 180;
                var dst = 105;
                var px = 150 + dst * Math.cos(rd);
                var py = 150 + dst * Math.sin(rd);
                var nameTag = document.createElement('span');
                nameTag.className = 'wheel-name';
                nameTag.textContent = persons[i].name;
                var fSize = n > 12 ? 10 : (n > 8 ? 11 : 12);
                nameTag.style.cssText = 'position:absolute;left:' + px + 'px;top:' + py + 'px;transform:translate(-50%,-50%);font-size:' + fSize + 'px;font-weight:800;color:#fff;text-shadow:0 1px 3px rgba(0,0,0,0.8),0 0 8px rgba(0,0,0,0.3);white-space:nowrap;pointer-events:none;z-index:3;letter-spacing:0.5px;';
                wheel.appendChild(nameTag);
            }

            // 中心圆
            var centerFaces = ['❓','🔧','⚡','🤔','💻','🔨','🛠️','🧰','🎯'];
            var center = document.createElement('div');
            center.textContent = centerFaces[Math.floor(Math.random() * centerFaces.length)];
            center.style.cssText = 'position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:64px;height:64px;border-radius:50%;background:radial-gradient(circle at 35% 35%,#fbbf24,#b45309);box-shadow:0 0 20px rgba(251,191,36,0.4),inset 0 -2px 4px rgba(0,0,0,0.2);z-index:5;border:3px solid rgba(255,255,255,0.15);display:flex;align-items:center;justify-content:center;font-size:28px;line-height:1;';

            wheelWrap.appendChild(pointer);
            wheelWrap.appendChild(wheel);
            wheelWrap.appendChild(center);
            modal.appendChild(wheelWrap);

            // 按钮区
            var btnWrap = document.createElement('div');
            btnWrap.style.cssText = 'display:flex;gap:10px;justify-content:center;min-height:48px;align-items:center;flex-direction:column;';
            modal.appendChild(btnWrap);

            // 转动中文字
            var spinTexts = ['🌀 转起来！转起来！','🎡 命运的齿轮...','🔄 选中那个幸运儿！','🎲 天灵灵地灵灵...','🪄 阿瓦达索命维修！','🌪️ 维修龙卷风来袭！','💫 让幸运女神降临！','🔥 燃烧吧！工单魂！'];

            // 🏆 抽奖成就
            var totalSpins = parseInt(localStorage.getItem('lotteryTotalSpins') || '0');

            // ===== 自动开转 =====
            function doSpin() {
                btnWrap.innerHTML = '';

                // 🔊 #4 模拟音效
                var soundText = document.createElement('div');
                soundText.style.cssText = 'color:rgba(251,191,36,0.5);font-size:11px;font-weight:600;letter-spacing:2px;font-family:monospace;margin-bottom:4px;';
                soundText.textContent = '🔊 ';
                btnWrap.appendChild(soundText);

                var loadingText = document.createElement('span');
                loadingText.id = 'spinLoading';
                var rText = spinTexts[Math.floor(Math.random() * spinTexts.length)];
                loadingText.textContent = rText;
                loadingText.style.cssText = 'color:rgba(251,191,36,0.7);font-size:14px;font-weight:600;';

                var dots = document.createElement('span');
                dots.id = 'spinDots';
                dots.textContent = '';
                loadingText.appendChild(dots);
                btnWrap.appendChild(loadingText);

                // 🎯 #9 整蛊奖品混入（10%概率）
                var prankItems = ['🫵 你自己上','☕ 请全组喝奶茶','🐛 放了个假虫','🧋 请喝奶茶','🎂 今天你请客','🛌 今天通宵值班'];
                if (Math.random() < 0.1) {
                    var prank = prankItems[Math.floor(Math.random() * prankItems.length)];
                    persons.push({name: prank, color: '#2d2d2d', isPrank: true});
                    n = persons.length;
                    angleStep = 360 / n;
                    var newStops = [];
                    for (var pi = 0; pi < n; pi++) {
                        persons[pi].color = funColors[pi % funColors.length];
                        var pst = pi * angleStep;
                        var pen = (pi + 1) * angleStep;
                        newStops.push(persons[pi].color + ' ' + pst + 'deg ' + pen + 'deg');
                    }
                    wheel.style.background = 'conic-gradient(' + newStops.join(',') + ')';
                    var oldNames = wheel.querySelectorAll('.wheel-name');
                    for (var oi = 0; oi < (oldNames ? oldNames.length : 0); oi++) if (oldNames[oi]) oldNames[oi].remove();
                    for (var pi = 0; pi < n; pi++) {
                        var aD2 = pi * angleStep + angleStep / 2;
                        var rd2 = (aD2 - 90) * Math.PI / 180;
                        var dst2 = 105;
                        var px2 = 150 + dst2 * Math.cos(rd2);
                        var py2 = 150 + dst2 * Math.sin(rd2);
                        var nt2 = document.createElement('span');
                        nt2.className = 'wheel-name';
                        nt2.textContent = persons[pi].name;
                        var fs2 = n > 12 ? 10 : (n > 8 ? 11 : 12);
                        nt2.style.cssText = 'position:absolute;left:' + px2 + 'px;top:' + py2 + 'px;transform:translate(-50%,-50%);font-size:' + fs2 + 'px;font-weight:800;color:#fff;text-shadow:0 1px 3px rgba(0,0,0,0.8),0 0 8px rgba(0,0,0,0.3);white-space:nowrap;pointer-events:none;z-index:3;letter-spacing:0.5px;';
                        wheel.appendChild(nt2);
                    }
                }

                // 🔊 #4 咔咔咔动画
                var clickChars = ['咔','嗒','哒','咯','吱','啪','咚'];
                var soundInt = setInterval(function() {
                    var c = clickChars[Math.floor(Math.random() * clickChars.length)];
                    var extra = Math.random() > 0.7 ? clickChars[Math.floor(Math.random() * clickChars.length)] : '';
                    soundText.textContent = '🔊 ' + c + extra + ' ';
                    soundText.style.opacity = 0.4 + Math.random() * 0.4;
                }, 150);

                // 省略号动画
                var dotCount = 0;
                var dotInt = setInterval(function() {
                    dotCount = (dotCount + 1) % 4;
                    dots.textContent = '.'.repeat(dotCount);
                }, 400);

                // 🎯 #8 多人抽取：额外抽2人
                var runnerUpIndices = [];
                while (runnerUpIndices.length < 2 && runnerUpIndices.length < n - 1) {
                    var ri = Math.floor(Math.random() * n);
                    if (runnerUpIndices.indexOf(ri) === -1) runnerUpIndices.push(ri);
                }

                var newWin = Math.floor(Math.random() * n);
                var newSpins = 5 + Math.floor(Math.random() * 3);
                var newAngle = newSpins * 360 + (360 - (newWin * angleStep + angleStep / 2));
                wheel.style.transition = 'transform 4s cubic-bezier(0.17,0.67,0.12,0.99)';
                wheel.style.transform = 'rotate(' + newAngle + 'deg)';

                // 🔊 #1 震动反馈
                if (navigator.vibrate) navigator.vibrate(30);

                var spinCenter = ['🌀','🌀','🎡','🔄','🤞'];
                center.textContent = spinCenter[Math.floor(Math.random() * spinCenter.length)];

                setTimeout(function() {
                    clearInterval(soundInt);
                    clearInterval(dotInt);
                    var winner = persons[newWin];
                    center.textContent = '🎉';

                    if (navigator.vibrate) navigator.vibrate([50,30,80]);

                    // 🕵️ #6 暗彩蛋（1%概率）
                    var isSecret = Math.random() < 0.01;
                    var secretTexts = ['🎁 隐藏大奖！你今天不用干活！','🕵️ 你发现了系统的秘密后门','🌟 恭喜获得「运维至尊」称号','💎 隐藏成就：命运掌控者','👑 你就是系统的主人'];

                    btnWrap.innerHTML = '';
                    var resultDiv = document.createElement('div');
                    resultDiv.style.cssText = 'padding:12px 18px;border-radius:16px;background:rgba(251,191,36,0.1);border:1px solid rgba(251,191,36,0.25);animation:resultPop 0.5s cubic-bezier(0.34,1.56,0.64,1);width:100%;';

                    if (isSecret) {
                        var secret = secretTexts[Math.floor(Math.random() * secretTexts.length)];
                        resultDiv.style.borderColor = 'rgba(255,107,107,0.5)';
                        resultDiv.style.background = 'rgba(255,107,107,0.12)';
                        resultDiv.innerHTML = '<div style="color:#ff6b6b;font-size:14px;font-weight:800;margin-bottom:3px;">🌟🌟🌟 EXTRA!!! 🌟🌟🌟</div>' +
                            '<div style="color:#fff;font-size:18px;font-weight:700;">' + secret + '</div>';
                    } else {
                        var ribTexts = ['🏆 天选打工人','🔧 维修の神','🧰 工具人认证','💪 搬砖小能手','⭐ 今日幸运星','🎯 被命运选中','🛠️ 螺丝钉之星','🌟 超级运维侠'];
                        var rib = ribTexts[Math.floor(Math.random() * ribTexts.length)];
                        var runnerUpText = '';
                        if (runnerUpIndices.length > 0) {
                            var medals = ['🥈','🥉'];
                            var ruNames = [];
                            for (var ri = 0; ri < runnerUpIndices.length; ri++) {
                                ruNames.push(medals[ri] + ' ' + persons[runnerUpIndices[ri]].name);
                            }
                            runnerUpText = '<div style="color:rgba(255,255,255,0.3);font-size:11px;margin-top:4px;">' + ruNames.join(' &nbsp;') + '</div>';
                        }
                        resultDiv.innerHTML = '<div style="color:rgba(251,191,36,0.7);font-size:12px;font-weight:600;margin-bottom:3px;">' + rib + '</div>' +
                            '<div style="color:#fff;font-size:26px;font-weight:900;text-shadow:0 0 20px rgba(251,191,36,0.3);">' + winner.name + '</div>' +
                            runnerUpText;
                    }

                    // 🌟 #5 金色闪烁高亮
                    var flashInterval = setInterval(function() {
                        var currentShadow = wheel.style.boxShadow;
                        if (currentShadow && currentShadow.indexOf('rgba(255,215,0') >= 0) {
                            wheel.style.boxShadow = '0 0 0 6px rgba(255,255,255,0.1),0 0 0 10px rgba(0,0,0,0.3),0 0 40px rgba(251,191,36,0.2)';
                        } else {
                            wheel.style.boxShadow = '0 0 0 6px rgba(255,215,0,0.6),0 0 0 10px rgba(0,0,0,0.3),0 0 50px rgba(255,215,0,0.4)';
                        }
                    }, 500);
                    setTimeout(function() { clearInterval(flashInterval); }, 3000);

                    // 🏆 #7 成就计数
                    totalSpins++;
                    localStorage.setItem('lotteryTotalSpins', String(totalSpins));
                    var achiMsgs = {10:'🏅 抽奖新手',25:'🎪 转盘常客',50:'👑 转盘之王',100:'💎 抽奖传说'};
                    var achiThresholds = [10,25,50,100];
                    for (var ai = 0; ai < achiThresholds.length; ai++) {
                        if (totalSpins === achiThresholds[ai]) {
                            setTimeout(function() {
                                if (window.showToast) showToast('🎉 成就达成：' + (achiMsgs[totalSpins] || '🏆 抽奖达人 x' + totalSpins), 'success');
                            }, 600);
                            var achiBanner = document.createElement('div');
                            achiBanner.style.cssText = 'margin-top:8px;padding:6px 12px;border-radius:10px;background:linear-gradient(135deg,rgba(251,191,36,0.2),rgba(255,107,107,0.2));border:1px solid rgba(251,191,36,0.3);animation:resultPop 0.5s ease-out;';
                            achiBanner.innerHTML = '<span style="font-size:16px;">' + (achiMsgs[totalSpins] || '🏆') + '</span>';
                            btnWrap.appendChild(achiBanner);
                            break;
                        }
                    }

                    var againBtn = document.createElement('button');
                    againBtn.textContent = '🔄 再抽一次';
                    againBtn.style.cssText = 'padding:8px 22px;border:none;border-radius:12px;background:rgba(251,191,36,0.15);color:#fbbf24;font-weight:700;font-size:13px;cursor:pointer;transition:all 0.15s;margin-left:10px;';
                    againBtn.onmouseover = function(){this.style.background='rgba(251,191,36,0.25)';};
                    againBtn.onmouseout = function(){this.style.background='rgba(251,191,36,0.15)';};
                    againBtn.onclick = function() {
                        wheel.style.transition = 'none';
                        wheel.style.transform = 'rotate(0deg)';
                        wheel.style.boxShadow = '0 0 0 6px rgba(255,255,255,0.1),0 0 0 10px rgba(0,0,0,0.3),0 0 40px rgba(251,191,36,0.2)';
                        doSpin();
                    };

                    var doneBtn = document.createElement('button');
                    doneBtn.textContent = '👌 妥了';
                    doneBtn.style.cssText = 'padding:8px 18px;border:none;border-radius:12px;background:rgba(255,255,255,0.08);color:rgba(255,255,255,0.6);font-weight:600;font-size:13px;cursor:pointer;transition:all 0.15s;';
                    doneBtn.onmouseover = function(){this.style.background='rgba(255,255,255,0.15)';};
                    doneBtn.onmouseout = function(){this.style.background='rgba(255,255,255,0.08)';};
                    doneBtn.onclick = function() { overlay.remove(); };

                    resultDiv.style.marginBottom = '8px';
                    btnWrap.appendChild(resultDiv);

                    var actRow = document.createElement('div');
                    actRow.style.cssText = 'display:flex;gap:10px;justify-content:center;width:100%;';
                    actRow.appendChild(againBtn);
                    actRow.appendChild(doneBtn);
                    btnWrap.appendChild(actRow);

                    // 彩纸
                    for (var ci = 0; ci < 25; ci++) {
                        (function() {
                            var c = document.createElement('div');
                            var cc = ['#fbbf24','#FF6B6B','#4DABF7','#69DB7C','#DA77F2','#FECA57','#FFA94D'];
                            var sz = Math.random() * 8 + 4;
                            c.style.cssText = 'position:fixed;top:-10px;left:' + (Math.random() * 100) + '%;z-index:99999;pointer-events:none;' +
                                'width:' + sz + 'px;height:' + sz + 'px;' +
                                'background:' + cc[Math.floor(Math.random() * cc.length)] + ';border-radius:' + (Math.random() > 0.5 ? '50%' : '2px') + ';' +
                                'animation:confettiFall ' + (Math.random() * 2 + 1.5) + 's ease-in ' + (Math.random() * 0.5) + 's forwards;opacity:0;';
                            document.body.appendChild(c);
                            setTimeout(function() { c.remove(); }, 4000);
                        })();
                    }

                    if (window.showToast) {
                        if (isSecret) showToast('🌟🌟🌟 ' + secretTexts[Math.floor(Math.random() * secretTexts.length)], 'success');
                        else showToast('🎉 抽中：' + winner.name, 'success');
                    }
                }, 4300);
            }

            // 弹窗出现后立刻开转
            setTimeout(function() { doSpin(); }, 400);
        }
    })();

    // ===== 🥚 彩蛋：连击侧边栏Logo =====
    (function() {
        var trigger = document.getElementById('brandTrigger');
        if (!trigger) return;
        var clicks = 0;
        var timer = null;
        var easterEggs = [
            { text: '⚡ 运维智脑已激活', icon: '🧠' },
            { text: '🔮 系统深度扫描中...', icon: '🔮' },
            { text: '🚀 工单引擎加速！', icon: '🚀' },
            { text: '💎 彩蛋模式启动！', icon: '💎' },
            { text: '🌟 全栈运维模式！', icon: '🌟' },
            { text: '🔥 你已经发现了秘密！', icon: '🔥' },
            { text: '🎉 恭喜！彩蛋解锁！', icon: '🎉' },
        ];

        trigger.addEventListener('click', function(e) {
            clicks++;
            if (timer) clearTimeout(timer);
            
            // 每次点击小反馈
            var icon = this.querySelector('.brand-icon');
            icon.style.transform = 'scale(1.2)';
            setTimeout(function() { icon.style.transform = ''; }, 200);

            if (clicks >= 7) {
                clicks = 0;
                // 触发彩蛋
                var egg = easterEggs[Math.floor(Math.random() * easterEggs.length)];
                
                // 创建全屏彩蛋动画
                var overlay = document.createElement('div');
                overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;z-index:99999;pointer-events:none;display:flex;align-items:center;justify-content:center;';
                
                // 主文字
                var text = document.createElement('div');
                text.style.cssText = 'font-size:48px;font-weight:900;color:#6366f1;text-shadow:0 0 40px rgba(99,102,241,0.5);animation:eggPop 0.8s cubic-bezier(0.34,1.56,0.64,1);background:rgba(15,23,42,0.7);backdrop-filter:blur(20px);padding:30px 50px;border-radius:20px;border:1px solid rgba(99,102,241,0.2);text-align:center;';
                text.innerHTML = egg.icon + '<br><span style="font-size:24px;margin-top:10px;display:block;">' + egg.text + '</span>';
                overlay.appendChild(text);
                document.body.appendChild(overlay);

                // 添加keyframes
                if (!document.getElementById('eggKeyframes')) {
                    var style = document.createElement('style');
                    style.id = 'eggKeyframes';
                    style.textContent = '@keyframes eggPop{0%{opacity:0;transform:scale(0.3) rotate(-10deg);}60%{transform:scale(1.1) rotate(2deg);}100%{opacity:1;transform:scale(1) rotate(0deg);}}';
                    document.head.appendChild(style);
                }

                // 创建彩纸
                for (var i = 0; i < 30; i++) {
                    (function() {
                        var confetti = document.createElement('div');
                        var colors = ['#6366f1','#06b6d4','#8b5cf6','#f59e0b','#10b981','#ef4444','#ec4899'];
                        var size = Math.random() * 10 + 6;
                        var color = colors[Math.floor(Math.random() * colors.length)];
                        var left = Math.random() * 100;
                        var delay = Math.random() * 0.8;
                        var dur = Math.random() * 2 + 1;
                        var isCircle = Math.random() > 0.5;
                        confetti.style.cssText = 'position:fixed;top:-20px;left:' + left + '%;z-index:99999;pointer-events:none;' +
                            'width:' + size + 'px;height:' + (isCircle ? size : size * 0.6) + 'px;' +
                            'background:' + color + ';border-radius:' + (isCircle ? '50%' : '2px') + ';' +
                            'animation:confettiFall ' + dur + 's ease-in ' + delay + 's forwards;opacity:0;';
                        document.body.appendChild(confetti);
                        setTimeout(function() { confetti.remove(); }, (dur + delay) * 1000 + 200);
                    })();
                }

                // 添加confetti keyframes
                if (!document.getElementById('confettiKeyframes')) {
                    var cs = document.createElement('style');
                    cs.id = 'confettiKeyframes';
                    cs.textContent = '@keyframes confettiFall{0%{opacity:1;transform:translateY(0) rotate(0deg) scale(0);}50%{opacity:1;transform:translateY(50vh) rotate(360deg) scale(1);}100%{opacity:0;transform:translateY(100vh) rotate(720deg) scale(0.5);}}';
                    document.head.appendChild(cs);
                }

                // 3秒后移除
                setTimeout(function() { overlay.remove(); }, 3000);

                // 显示toast通知
                if (window.showToast) {
                    showToast('🎉 ' + egg.text, 'success');
                }
            } else {
                // 重置计时器 - 2秒内要完成7连击
                timer = setTimeout(function() { clicks = 0; }, 2000);
            }
        });
    })();

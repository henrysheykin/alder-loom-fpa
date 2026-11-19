from core import *

def build_reservations(ds):
    rng=ds.rng;closures={};maintenance=[]
    for rid,r in ds.rooms.items():
        p=r['property_id'];num=int(r['room_number']);spans=[]
        if p=='WIL' and 102<=num<=109: spans.append((date(2026,2,2),date(2026,3,16),'OOO','refurbishment'))
        if p=='RAL' and 102<=num<=105: spans.append((date(2026,7,10),date(2026,7,21),'OOO','HVAC failure'))
        # Preventive work and deep-clean intervals exist independently of reservations.
        d=START+timedelta(days=(num*19)%520+20)
        duration=2 if num%3==0 else 1
        while any(d<b and d+timedelta(days=duration)>a for a,b,status,reason in spans):
            d=max(b for a,b,status,reason in spans if d<b and d+timedelta(days=duration)>a)+timedelta(days=7)
        spans.append((d,d+timedelta(days=2 if num%3==0 else 1),'OOS','preventive service'))
        for a,b,status,reason in spans:
            wid=ds.ident('WO');bid=ds.ident('BLK')
            ds.add('operations/work_orders','work_order_id','One maintenance job with exclusive end date',work_order_id=wid,property_id=p,room_id=rid,opened_date=iso(a-timedelta(days=5)),planned_start_date=iso(a),planned_end_date=iso(b),actual_start_date=iso(a),actual_completed_date=iso(b-timedelta(days=1)),work_type=reason,capitalized=reason=='refurbishment',block_id=bid,approved_cost_usd=180000 if reason=='refurbishment' else 46000 if reason=='HVAC failure' else 14500)
            ds.add('availability/room_blocks','block_id','One room closure interval; end_date exclusive',block_id=bid,room_id=rid,property_id=p,start_date=iso(a),end_date=iso(b),block_status=status,work_order_id=wid,reason=reason,excluded_from_internal_availability=True)
            for day in nights(a,b,FUT): closures[(rid,day)]=(bid,status,wid)
    protected={('RAL-101',day) for day in nights(date(2026,10,29),date(2026,11,3),FUT)}|{('WIL-101',day) for day in nights(date(2026,10,25),date(2026,10,29),FUT)}
    rate_versions={r['rate_plan_version_id']:r for r in ds.tables['pms/rate_plans']}
    def create(rid,a,b,forced=None,status='stay'):
        room=ds.rooms[rid];p=room['property_id'];n=(b-a).days
        idx=ds.seq['RSV']+1;resid=ds.ident('RSV');guest=f'GST-{(idx*17)%14000+1:06d}'
        iscorp=(p=='DUR' and n>=14) or (p!='DUR' and rng.random()<.16)
        internal=rng.random()<.009 and status=='stay' and not forced
        comp=internal and rng.random()<.65
        company=f'CO-{rng.randint(1,6):03d}' if iscorp and not internal else ''
        if internal: channel='INTERNAL'
        elif iscorp: channel='CORPORATE'
        else:
            direct=.43 if a<date(2025,4,1) else .56 if a<date(2026,6,1) else .40
            pick=rng.random();channel='DIRECT' if pick<direct else 'BOOKING' if pick<direct+.29 else 'EXPEDIA'
        if forced: channel=forced;company='';internal=False;comp=False
        collection={'DIRECT':'hotel_collect','BOOKING':'agency','EXPEDIA':'merchant','CORPORATE':'invoice','INTERNAL':'internal'}[channel]
        prepaid=channel in ['DIRECT','BOOKING'] and (rng.random()<.46 or forced=='DIRECT')
        rate_code='COMP' if internal else 'EXTENDED' if p=='DUR' and n>=14 else 'CORP' if company else 'ADVANCE' if prepaid else 'BAR'
        lead=rng.randint(3,55) if n<14 else rng.randint(10,65)
        booking=a-timedelta(days=lead)
        if forced=='DIRECT': booking=date(2026,10,20)
        if forced=='EXPEDIA': booking=date(2026,9,22)
        if booking>CUT: return
        cancelled=status=='cancelled';noshow=status=='no_show'
        canceldate=max(START,booking,a-timedelta(days=rng.randint(1,8))) if cancelled else None
        if canceldate and canceldate>CUT: return
        actualn=list(nights(a,b)) if status=='stay' else []
        plan=[]
        for d in nights(a,b,FUT+timedelta(days=90)):
            version='V1' if d<date(2026,3,1) else 'V2';rp=rate_versions[f'{p}-{rate_code}-{version}']
            base,mult=ds.types[room['room_type_id']]
            season=1+.13*__import__('math').sin((d.month-3)*__import__('math').pi/6) if p=='WIL' else 1+.045*__import__('math').sin((d.month-2)*__import__('math').pi/6)
            weekday=1.18 if p=='WIL' and d.weekday() in [4,5] else 1.06 if p=='RAL' and d.weekday()<4 else .94 if p=='RAL' else 1
            annual=1.08 if d>=date(2026,3,1) else 1
            gross=mul(base,mult*season*weekday*annual*(.985+(idx%7)*.005)) if not internal else 0
            discount=mul(gross,Decimal('1')-Decimal(str(rp['base_multiplier'])))
            net=gross-discount;tax=mul(net,.125 if p=='WIL' else .1125)
            plan.append(dict(service_date=d,gross=gross,discount=discount,net=net,tax=tax,rate_version=rp['rate_plan_version_id']))
        quoted_room=sum(x['net'] for x in plan);quoted_tax=sum(x['tax'] for x in plan)
        current='cancelled' if cancelled else 'no_show' if noshow else 'checked_out' if b<=CUT else 'in_house' if a<=CUT else 'confirmed'
        row=ds.add('pms/reservations','reservation_id','One room reservation snapshot; future confirmed != actual stay',reservation_id=resid,booking_id=resid.replace('RSV','BKG'),property_id=p,guest_id=guest,company_id=company,contract_id=f'CT-{company}-{p}' if company else '',channel_id=channel,collection_model=collection,booked_date=iso(booking),scheduled_checkin_date=iso(a),scheduled_checkout_date=iso(b),actual_checkin_date=iso(a) if actualn else '',actual_checkout_date=iso(b) if actualn and b<=CUT else '',cancellation_date=iso(canceldate) if canceldate else '',status_as_of_cutoff=current,room_type_id=room['room_type_id'],assigned_room_id=rid,rate_plan_code=rate_code,planned_nights=n,actual_consumed_nights=len(actualn),adults=2 if rng.random()<.6 else 1,stay_category='extended_corporate' if n>=14 and company else 'short_stay',is_complimentary=comp,is_house_use=internal and not comp,prepaid=prepaid,quoted_room_usd=quoted_room,quoted_lodging_tax_usd=quoted_tax,quoted_total_usd=quoted_room+quoted_tax,snapshot_date=iso(CUT))
        row['_plan']=plan;row['_a']=a;row['_b']=b;row['_kind']=status;ds.res.append(row)
        for j,(event,ed) in enumerate([('created',booking)]+([('rate_reviewed',max(booking,a-timedelta(days=2)))] if idx%13==0 else [])+([('cancelled',canceldate)] if cancelled else [('no_show',a)] if noshow else [('checked_in',a)]+([('checked_out',b)] if b<=CUT else []))):
            if ed and ed<=CUT:
                ds.add('pms/reservation_history','history_id','One recorded status/modification event; not a second booking',history_id=ds.ident('HIS'),reservation_id=resid,event_date=iso(ed),event_type=event,previous_value='pending' if event=='rate_reviewed' else '',new_value='confirmed category rate' if event=='rate_reviewed' else event,changed_by='synthetic_pms',event_sequence=j+1)
        if idx%29==0:
            ed=max(booking,min(a-timedelta(days=1),CUT))
            ds.add('pms/reservation_modifications','modification_id','One reservation amendment with old/new scheduled fields',modification_id=ds.ident('MOD'),reservation_id=resid,modified_date=iso(ed),field_name='scheduled_checkout_date',old_value=iso(b-timedelta(days=1)),new_value=iso(b),reason='guest extension before arrival')
        ds.add('pms/room_assignments','assignment_id','One confirmed assignment per room reservation',assignment_id=ds.ident('ASN'),reservation_id=resid,room_id=rid,property_id=p,assigned_date=iso(min(CUT, max(booking,a-timedelta(days=2)))),start_date=iso(a),end_date=iso(b),assignment_state='released' if cancelled or noshow else 'actual' if a<=CUT else 'planned')
        for x in plan:
            d=x['service_date']
            if d<=CUT and status=='stay':
                nid=f'N-{resid}-{d.isoformat()}'
                ds.add('pms/actual_stay_nights','stay_night_id','One actually consumed assigned room-night; checkout excluded',stay_night_id=nid,reservation_id=resid,property_id=p,room_id=rid,service_date=iso(d),stay_status='house_use' if internal and not comp else 'complimentary' if comp else 'sold',sold_nights=0 if internal else 1,occupied_nights=1,rate_plan_version_id=x['rate_version'])
                ds.room_dates[(rid,d)]=(resid,'house_use' if internal and not comp else 'complimentary' if comp else 'sold',nid)
            elif d>CUT and status=='stay':
                ds.add('planning/on_books_nights','on_books_night_id','One known booked future room-night at cutoff; not actual revenue',on_books_night_id=f'OTB-{resid}-{iso(d)}',snapshot_date=iso(CUT),reservation_id=resid,property_id=p,room_id=rid,service_date=iso(d),channel_id=channel,collection_model=collection,booked_room_usd=x['net'],booked_lodging_tax_usd=x['tax'],contract_id=row['contract_id'],is_sold_commitment=not internal)
        return row
    for rid,room in ds.rooms.items():
        p=room['property_id'];d=START+timedelta(days=rng.randint(0,3))
        while d<=FUT:
            if (rid,d) in closures or (rid,d) in protected: d+=timedelta(days=1);continue
            seasonal=.62+.17*__import__('math').sin((d.month-3)*__import__('math').pi/6) if p=='WIL' else .68+.04*__import__('math').sin((d.month-2)*__import__('math').pi/6) if p=='RAL' else .77
            if d>=date(2026,5,1): seasonal-=.09 if p=='WIL' else .045 if p=='RAL' else .015
            if p=='WIL' and d.weekday() in [4,5]: seasonal+=.05
            mean=23 if p=='DUR' else 3.0
            q=seasonal/(mean*(1-seasonal)+seasonal)
            if rng.random()>q: d+=timedelta(days=1);continue
            length=rng.randint(14,55) if p=='DUR' and rng.random()<.79 else rng.choices([1,2,3,4,5,6],[14,25,30,17,10,4])[0]
            b=d+timedelta(days=length)
            if any((rid,x) in closures or (rid,x) in protected for x in nights(d,b,FUT+timedelta(days=60))): d+=timedelta(days=1);continue
            create(rid,d,b);d=b
    ds.trace_direct=create('RAL-101',date(2026,10,29),date(2026,11,3),'DIRECT')
    ds.trace_ota=create('WIL-101',date(2026,10,25),date(2026,10,29),'EXPEDIA')
    # Separate requests which never consumed capacity, including before cutoff cancellations of future arrivals.
    successful=list(ds.res)
    for base in rng.sample(successful,min(len(successful),int(len(successful)*.12))):
        a=base['_a'];b=a+timedelta(days=rng.randint(1,4))
        if a>CUT-timedelta(days=5): a=CUT-timedelta(days=rng.randint(5,30));b=a+timedelta(days=2)
        create(base['assigned_room_id'],a,b,status='cancelled' if rng.random()<.87 else 'no_show')
    # Multi-room mapping groups same-property/date reservations; one component still equals one assigned room.
    pools=defaultdict(list)
    for r in ds.res:
        if r['_kind']=='stay': pools[(r['property_id'],r['scheduled_checkin_date'],r['company_id'],r['channel_id'])].append(r)
    for key,rr in pools.items():
        if len(rr)>=2 and (key[2] or rng.random()<.18):
            bid=ds.ident('GRP');selected=rr[:min(4,len(rr))]
            for r in selected:r['booking_id']=bid
    # _fields removed later; keep source snapshot pure.
    bybooking=defaultdict(list)
    for r in ds.res:bybooking[r['booking_id']].append(r)
    for bid,rr in bybooking.items():
        ds.add('pms/bookings','booking_id','One single-room or multi-room booking group',booking_id=bid,property_id=rr[0]['property_id'],created_date=min(r['booked_date'] for r in rr),booker_guest_id=rr[0]['guest_id'],company_id=rr[0]['company_id'],room_reservation_count=len(rr))
        for i,r in enumerate(rr,1):
            ds.add('pms/booking_rooms','booking_room_id','One booking-to-room-reservation mapping',booking_room_id=ds.ident('BKR'),booking_id=bid,reservation_id=r['reservation_id'],room_sequence=i)
    guest_ids=sorted({r['guest_id'] for r in ds.res})
    for gid in guest_ids:
        ds.add('pms/guests','guest_id','One synthetic guest identifier; no personal data',guest_id=gid,display_name=f'Synthetic guest {gid[-6:]}',email=f'{gid.lower()}@example.com',country_code='US')
    arrivals={(r['assigned_room_id'],r['actual_checkin_date']) for r in ds.res if r['actual_checkin_date']}
    departures={(r['assigned_room_id'],r['actual_checkout_date']) for r in ds.res if r['actual_checkout_date']}
    for rid,r in ds.rooms.items():
        for d in days():
            block=closures.get((rid,d));occ=ds.room_dates.get((rid,d));bid,bs,wid=block if block else ('','','')
            typ=occ[1] if occ else ''
            arrival=int((rid,iso(d)) in arrivals);departure=int((rid,iso(d)) in departures)
            ds.add('availability/room_dates','room_id,service_date','One physical room per service date; additive capacity measures',room_id=rid,property_id=r['property_id'],service_date=iso(d),physical_nights=1,out_of_order_nights=int(bs=='OOO'),out_of_service_nights=int(bs=='OOS'),available_nights=int(not block),sold_nights=int(typ=='sold'),complimentary_nights=int(typ=='complimentary'),house_use_nights=int(typ=='house_use'),occupied_nights=int(bool(occ)),vacant_available_nights=int(not block and not occ),arrivals_count=arrival,departures_count=departure,same_day_turnovers_count=arrival*departure,block_id=bid,reservation_id=occ[0] if occ else '',stay_night_id=occ[2] if occ else '')
    # Future capacity independent from known bookings; no invented future consumed nights.
    for d in days(CUT+timedelta(days=1),FUT):
        for p in PROPS:
            ds.add('planning/future_capacity','property_id,service_date','One forecast date/property physical capacity assumption',property_id=p,service_date=iso(d),snapshot_date=iso(CUT),physical_nights=COUNTS[p],known_closed_nights=0,available_nights=COUNTS[p],assumption_id='FC-BASE')

def build_folios_and_collections(ds):
    rng=ds.rng
    channels={r['channel_id']:r for r in ds.tables['channel_manager/channels']}
    ds.gateway=[];ds.ota_items=[];ds.corp_lines=defaultdict(list);ds.deposit_movements=[]
    def folio(r,d,kind,gross,discount=0,original='',taxable=False,nightid=''):
        net=gross-discount;tax=mul(net,.125 if r['property_id']=='WIL' else .1125) if taxable else 0
        fid=ds.ident('FOL');p=r['property_id'];res=r['reservation_id']
        account={'room':'4000','room_credit':'4020','parking':'4100','breakfast':'4110','cleaning':'4120','late_checkout':'4120','cancellation_fee':'4200','no_show_fee':'4210'}[kind]
        debit='1120' if r['collection_model']=='merchant' else '1130' if r['company_id'] else '1110'
        taxacc='2110' if r['collection_model']=='merchant' else '2100'
        row=ds.add('night_audit/folio_lines','folio_line_id','One earned service charge or credit; signed USD; invoices copy/reclass only',folio_line_id=fid,folio_id=f'FO-{res}',reservation_id=res,stay_night_id=nightid,property_id=p,service_date=iso(d),posting_date=iso(d),charge_type=kind,original_folio_line_id=original,gross_amount_usd=gross,discount_amount_usd=discount,net_revenue_usd=net,tax_usd=tax,total_charge_usd=net+tax,receivable_account_code=debit,revenue_account_code=account,tax_account_code=taxacc if tax else '',collection_model=r['collection_model'],currency='USD')
        entries=[(p,debit,net+tax),(p,account,-gross)]
        if discount: entries.append((p,'4010',discount))
        if tax:entries.append((p,taxacc,-tax))
        ds.post(d,'night_audit','folio_lines',fid,entries,kind)
        ds.charges[res].append(row)
        if r['company_id']:ds.corp_lines[(r['company_id'],p,iso(d)[:7])].append(row)
        if r['channel_id'] in ['BOOKING','EXPEDIA'] and kind in ['room','room_credit','cancellation_fee','no_show_fee']:
            commission=mul(net,channels[r['channel_id']]['commission_rate']);ci=ds.ident('COM')
            ds.add('channel_manager/commissions','commission_id','One commission accrual or adjustment linked to earned folio line',commission_id=ci,reservation_id=res,folio_line_id=fid,property_id=p,channel_id=r['channel_id'],service_date=iso(d),commission_base_usd=net,commission_rate=channels[r['channel_id']]['commission_rate'],commission_usd=commission,adjustment_type='credit_adjustment' if net<0 else 'earned_charge',settlement_id='')
            ds.post(d,'channel_manager','commissions',ci,[(p,'5000',commission),(p,'2010',-commission)],'distribution cost')
        return row
    def capture(r,d,amount,kind='lodging',refund=False,parent='',folio_id=''):
        if not amount or d>CUT:return None
        pid=ds.ident('PAY');p=r['property_id'];amount=abs(amount);signed=-amount if refund else amount
        fee=0 if refund else mul(amount,.0275)+25
        liability='2210' if kind=='security' else '2200' if kind=='lodging' else '1110'
        row=ds.add('payments/transactions','payment_id','One successful actual gateway capture/refund; no bank deposit revenue',payment_id=pid,reservation_id=r['reservation_id'],property_id=p,transaction_date=iso(d),transaction_type='refund' if refund else 'capture',purpose=kind,parent_payment_id=parent,folio_line_id=folio_id,gross_amount_usd=signed,processing_fee_usd=fee,net_processor_usd=signed-fee,currency='USD',liability_or_ar_account_code=liability,status='succeeded')
        ds.post(d,'payments','transactions',pid,[(p,'1010',signed-fee),(p,'5010',fee),(p,liability,-signed)],kind)
        ds.gateway.append(row);return row
    for r in ds.res:
        res=r['reservation_id'];p=r['property_id'];a=r['_a'];b=r['_b'];kind=r['_kind']
        actual=[x for x in r['_plan'] if x['service_date']<=CUT] if kind=='stay' else []
        # Revenue follows service, irrespective of invoice/checkout/payment dates.
        for j,x in enumerate(actual):
            d=x['service_date'];nid=f'N-{res}-{iso(d)}'
            if r['channel_id']=='INTERNAL':continue
            line=folio(r,d,'room',x['gross'],x['discount'],taxable=True,nightid=nid)
            if r['collection_model']!='merchant':
                if p!='DUR' and int(res[-4:])%4==0: folio(r,d,'parking',1800 if p=='RAL' else 1400,nightid=nid)
                if p!='DUR' and int(res[-4:])%3==0: folio(r,d,'breakfast',2400,nightid=nid)
            if j==len(r['_plan'])-1 and d<CUT and r['collection_model']!='merchant':
                if p=='DUR':folio(r,d,'cleaning',6500,nightid=nid)
                elif int(res[-4:])%11==0:folio(r,d,'late_checkout',3500,nightid=nid)
        # Separate earned fees for late cancellation/no-show; never an occupied night.
        fee_line=None
        if kind in ['cancelled','no_show'] and (kind=='no_show' or int(res[-4:])%4==0):
            d=date.fromisoformat(r['cancellation_date']) if kind=='cancelled' else a
            if d<=CUT: fee_line=folio(r,d,'cancellation_fee' if kind=='cancelled' else 'no_show_fee',r['_plan'][0]['net'])
        # Genuine service recovery credit, separate from original room revenue.
        credit=None
        if actual and r['channel_id']!='INTERNAL' and int(res[-4:])%61==0:
            orig=next((c for c in ds.charges[res] if c['charge_type']=='room'),None)
            if orig:
                d=min(b-timedelta(days=1),CUT);credit=folio(r,d,'room_credit',-mul(orig['net_revenue_usd'],.30),original=orig['folio_line_id'],taxable=True,nightid=orig['stay_night_id'])
        if r['channel_id']=='INTERNAL':continue
        lines=ds.charges[res];earned=sum(c['total_charge_usd'] for c in lines)
        if r['collection_model']=='merchant':
            if lines:
                # Merchant pays monthly earned amounts, even while a long reservation continues.
                ds.ota_items.extend((r,c) for c in lines)
            continue
        if r['company_id']:
            if kind=='stay' and r['contract_id'] and r['company_id'] in ['CO-001','CO-003']:
                dep=mul(r['quoted_total_usd'],.20);dd=max(START,date.fromisoformat(r['booked_date'])+timedelta(days=2))
                if dd<=CUT:
                    did=ds.ident('CDP');bid=ds.cash(dd,p,dep,'corporate_advance',did,'2220','corporate_billing','prepayments')
                    ds.add('corporate_billing/prepayments','prepayment_id','One actual corporate advance; application later is non-cash',prepayment_id=did,reservation_id=res,company_id=r['company_id'],property_id=p,payment_date=iso(dd),amount_usd=dep,bank_transaction_id=bid,applied_usd=0,open_amount_usd=dep)
            # Corporate security is a distinct refundable liability and cash event.
            if p=='DUR' and kind=='stay' and a<=CUT:
                sid=ds.ident('SEC');amount=25000;bid=ds.cash(a,p,amount,'security_deposit',sid,'2210','payments','security_movements')
                ds.add('payments/security_movements','security_movement_id','One refundable security cash movement; signed receipts positive',security_movement_id=sid,reservation_id=res,property_id=p,movement_date=iso(a),movement_type='receipt',amount_usd=amount,payment_id='',bank_transaction_id=bid)
                refund_date=plus_business(b,3)
                if refund_date<=CUT:
                    sid=ds.ident('SEC');bid=ds.cash(refund_date,p,-amount,'security_refund',sid,'2210','payments','security_movements')
                    ds.add('payments/security_movements','security_movement_id','One refundable security cash movement; signed receipts positive',security_movement_id=sid,reservation_id=res,property_id=p,movement_date=iso(refund_date),movement_type='refund',amount_usd=-amount,payment_id='',bank_transaction_id=bid)
            continue
        # Guest lodging deposit and its per-charge applications.
        paid=0;firstpay=None
        if kind=='stay':
            paydate=max(START,date.fromisoformat(r['booked_date'])+timedelta(days=2)) if r['prepaid'] else a
            deposit=r['quoted_total_usd'] if r['prepaid'] else sum(c['total_charge_usd'] for c in lines if c['charge_type'] not in ['room_credit'])
            if paydate<=CUT:
                firstpay=capture(r,paydate,deposit);paid=deposit
            if p=='DUR' and a<=CUT:
                sec=capture(r,a,25000,'security')
                ds.add('payments/security_movements','security_movement_id','One refundable security cash movement; signed receipts positive',security_movement_id=ds.ident('SEC'),reservation_id=res,property_id=p,movement_date=iso(a),movement_type='receipt',amount_usd=25000,payment_id=sec['payment_id'],bank_transaction_id='')
                rd=plus_business(b,3)
                if rd<=CUT:
                    sec2=capture(r,rd,25000,'security',True,sec['payment_id'])
                    ds.add('payments/security_movements','security_movement_id','One refundable security cash movement; signed receipts positive',security_movement_id=ds.ident('SEC'),reservation_id=res,property_id=p,movement_date=iso(rd),movement_type='refund',amount_usd=-25000,payment_id=sec2['payment_id'],bank_transaction_id='')
        elif r['prepaid']:
            pd=max(START,date.fromisoformat(r['booked_date'])+timedelta(days=2))
            rd=date.fromisoformat(r['cancellation_date']) if kind=='cancelled' else a
            retain=fee_line['total_charge_usd'] if fee_line else 0
            if rd<pd:
                # Cancelled before capture: void the lodging authorization and capture only an earned fee.
                if retain and rd<=CUT:firstpay=capture(r,rd,retain);paid=retain
            else:
                if pd<=CUT:firstpay=capture(r,pd,r['quoted_total_usd']);paid=r['quoted_total_usd']
                if paid>retain and rd<=CUT:
                    ref=capture(r,rd,paid-retain,'lodging',True,firstpay['payment_id']);paid=retain
        elif fee_line:
            firstpay=capture(r,date.fromisoformat(fee_line['service_date']),fee_line['total_charge_usd']);paid=fee_line['total_charge_usd']
        remaining=paid
        for c in [c for c in lines if c['total_charge_usd']>0]:
            amount=min(remaining,c['total_charge_usd']);remaining-=amount
            if amount:
                aid=ds.ident('APP');ad=max(date.fromisoformat(c['service_date']),date.fromisoformat(firstpay['transaction_date']))
                ds.add('payments/applications','application_id','One non-cash guest deposit application to an earned folio charge',application_id=aid,payment_id=firstpay['payment_id'],reservation_id=res,folio_line_id=c['folio_line_id'],property_id=p,application_date=iso(ad),amount_usd=amount,from_account_code='2200',to_account_code='1110')
                ds.post(ad,'payments','applications',aid,[(p,'2200',amount),(p,'1110',-amount)],'deposit earned')
            unpaid=c['total_charge_usd']-amount
            if unpaid:
                d=date.fromisoformat(c['service_date']);capture(r,d,unpaid,'folio',folio_id=c['folio_line_id'])
        if credit:
            rd=date.fromisoformat(credit['service_date']);capture(r,rd,-credit['total_charge_usd'],'folio',True,firstpay['payment_id'] if firstpay else '',credit['folio_line_id'])
        # Security liability forecasts identify expected return without recording future cash.
    # Gateway balance transactions settled in property-specific weekly batches.
    batches=defaultdict(list)
    for tx in ds.gateway:
        d=date.fromisoformat(tx['transaction_date']);available=plus_business(d,2)
        target=available+timedelta(days=(4-available.weekday())%7)
        key=(tx['property_id'],target)
        batches[key].append((tx,available))
    for (p,target),rr in sorted(batches.items()):
        created=target if target<=CUT else None;pid=ds.ident('PYO') if created else ''
        gross=sum(t['gross_amount_usd'] for t,a in rr);fees=sum(t['processing_fee_usd'] for t,a in rr);net=gross-fees
        bankdate=plus_business(target,1)
        bid=''
        if created:
            ds.post(target,'payments','payouts',pid,[(p,'1020',net),(p,'1010',-net)],'processor payout initiated')
            bid=ds.cash(bankdate,p,net,'gateway_payout',pid,'1020','payments','payouts')
            ds.add('payments/payouts','payout_id','One initiated gateway payout; blank bank date means in transit',payout_id=pid,property_id=p,created_date=iso(target),expected_bank_date=iso(bankdate),actual_bank_date=iso(bankdate) if bankdate<=CUT else '',gross_usd=gross,fees_usd=fees,net_payout_usd=net,balance_transaction_count=len(rr),bank_transaction_id=bid,status='paid' if bid else 'in_transit')
        for tx,available in rr:
            ds.add('payments/balance_transactions','balance_transaction_id','One processor ledger transaction linked once to a payment',balance_transaction_id=ds.ident('BTX'),payment_id=tx['payment_id'],property_id=p,transaction_date=tx['transaction_date'],expected_available_date=iso(available),actual_available_date=iso(available) if available<=CUT else '',gross_usd=tx['gross_amount_usd'],fee_usd=tx['processing_fee_usd'],net_usd=tx['net_processor_usd'],payout_id=pid,status_as_of_cutoff='paid' if bid else 'in_transit' if pid else 'available' if available<=CUT else 'pending')
    # OTA source reservation export is a mapping, never extra sales.
    for r in ds.res:
        if r['channel_id'] not in ['BOOKING','EXPEDIA']:continue
        ds.add('channel_manager/reservations','ota_reservation_id','One OTA reference mapped to PMS reservation',ota_reservation_id='OTA-'+r['reservation_id'],reservation_id=r['reservation_id'],listing_id=f'{r["channel_id"]}-{r["property_id"]}',channel_id=r['channel_id'],collection_model=r['collection_model'],external_booking_reference='SYN-'+r['reservation_id'],booked_date=r['booked_date'],status_as_of_cutoff=r['status_as_of_cutoff'],quoted_room_usd=r['quoted_room_usd'],quoted_tax_usd=r['quoted_lodging_tax_usd'])
    build_ota_settlements(ds)
    build_corporate_billing(ds)
    # Folio headers expose remaining guest AR; corporate/OTA balances live in their subledgers.
    app=defaultdict(int);folio_cash=defaultdict(int)
    for r in ds.tables['payments/applications']:app[r['folio_line_id']]+=r['amount_usd']
    for t in ds.gateway:
        if t['purpose']=='folio':folio_cash[t['folio_line_id']]+=t['gross_amount_usd']
    for r in ds.res:
        lines=ds.charges[r['reservation_id']]
        ds.add('night_audit/folios','folio_id','One reservation folio aggregate; earned charges only',folio_id=f'FO-{r["reservation_id"]}',reservation_id=r['reservation_id'],property_id=r['property_id'],net_revenue_usd=sum(c['net_revenue_usd'] for c in lines),tax_usd=sum(c['tax_usd'] for c in lines),total_charge_usd=sum(c['total_charge_usd'] for c in lines),guest_open_ar_usd=sum(c['total_charge_usd']-app[c['folio_line_id']]-folio_cash[c['folio_line_id']] for c in lines) if not r['company_id'] and r['collection_model']!='merchant' else 0)

def build_ota_settlements(ds):
    comms=defaultdict(list)
    for c in ds.tables['channel_manager/commissions']:comms[c['folio_line_id']].append(c)
    grouped=defaultdict(list)
    for r,c in ds.ota_items:
        d=date.fromisoformat(c['service_date']);# Weekly Saturdays: modeled contractual release, not native OTA timing.
        settle=d+timedelta(days=(5-d.weekday())%7+7)
        if r['reservation_id']==ds.trace_ota['reservation_id']:settle=date(2026,10,31)
        grouped[(r['property_id'],settle)].append((r,c))
    for (p,d),rr in sorted(grouped.items()):
        sid=ds.ident('OTS');gross=sum(c['total_charge_usd'] for r,c in rr);tax=sum(c['tax_usd'] for r,c in rr);comm=sum(x['commission_usd'] for r,c in rr for x in comms[c['folio_line_id']]);net=gross-tax-comm
        released=d<=CUT;expected=plus_business(d,1);bid=''
        if released:
            ds.post(d,'channel_manager','settlements',sid,[(p,'1120',-gross),(p,'2110',tax),(p,'2010',comm),(p,'1020',net)],'OTA gross AR cleared to net remittance')
            bid=ds.cash(expected,p,net,'ota_payout',sid,'1020','channel_manager','settlements')
        ds.add('channel_manager/settlements','settlement_id','One merchant release batch or expected unreleased settlement at cutoff',settlement_id=sid,property_id=p,channel_id='EXPEDIA',expected_release_date=iso(d),actual_release_date=iso(d) if released else '',expected_bank_date=iso(expected),actual_bank_date=iso(expected) if bid else '',gross_folio_usd=gross,commission_withheld_usd=comm,ota_remitted_tax_usd=tax,net_payout_usd=net,bank_transaction_id=bid,status='paid' if bid else 'in_transit' if released else 'expected')
        for r,c in rr:
            amount=sum(x['commission_usd'] for x in comms[c['folio_line_id']])
            ds.add('channel_manager/settlement_lines','settlement_line_id','One earned folio component mapped to merchant settlement',settlement_line_id=ds.ident('OSL'),settlement_id=sid,reservation_id=r['reservation_id'],folio_line_id=c['folio_line_id'],property_id=p,gross_folio_usd=c['total_charge_usd'],commission_usd=amount,ota_tax_usd=c['tax_usd'],net_usd=c['total_charge_usd']-amount-c['tax_usd'])
            for cm in comms[c['folio_line_id']]:cm['settlement_id']=sid
    agency=defaultdict(list)
    for c in ds.tables['channel_manager/commissions']:
        if c['channel_id']=='BOOKING':agency[(c['property_id'],c['service_date'][:7])].append(c)
    for (p,mo),rr in sorted(agency.items()):
        d=date.fromisoformat(mo+'-01');due=next_month(d)+timedelta(days=14);aid=ds.ident('ACI');amount=sum(x['commission_usd'] for x in rr)
        bid=ds.cash(due,p,-amount,'agency_commission',aid,'2010','channel_manager','agency_invoices')
        ds.add('channel_manager/agency_invoices','agency_invoice_id','One accrued agency commission period; payment clears payable only',agency_invoice_id=aid,property_id=p,channel_id='BOOKING',service_month=mo,invoice_date=iso(month_end(d)),due_date=iso(due),commission_usd=amount,paid_usd=amount if bid else 0,open_usd=0 if bid else amount,actual_payment_date=iso(due) if bid else '',bank_transaction_id=bid)
        for c in rr:c['settlement_id']=aid

def build_corporate_billing(ds):
    contracts={x['contract_id']:x for x in ds.tables['corporate_billing/contracts']};depbyres=defaultdict(list)
    for d in ds.tables['corporate_billing/prepayments']:depbyres[d['reservation_id']].append(d)
    for (co,p,mo),lines in sorted(ds.corp_lines.items(),key=lambda x:(x[0][2],x[0][0],x[0][1])):
        ct=contracts[f'CT-{co}-{p}'];end=month_end(date.fromisoformat(mo+'-01'));iid=ds.ident('INV');total=sum(c['total_charge_usd'] for c in lines);net=sum(c['net_revenue_usd'] for c in lines);tax=total-net
        ds.post(end,'corporate_billing','invoices',iid,[(p,'1100',total),(p,'1130',-total)],'invoice earned corporate folios; no new revenue')
        for c in lines:
            ds.add('corporate_billing/invoice_lines','invoice_line_id','One corporate invoice line mapped to one earned folio line',invoice_line_id=ds.ident('IVL'),invoice_id=iid,folio_line_id=c['folio_line_id'],reservation_id=c['reservation_id'],property_id=p,service_date=c['service_date'],net_usd=c['net_revenue_usd'],tax_usd=c['tax_usd'],total_usd=c['total_charge_usd'])
        applied=0
        for res in sorted({c['reservation_id'] for c in lines}):
            cap=sum(c['total_charge_usd'] for c in lines if c['reservation_id']==res)
            for dep in depbyres[res]:
                amount=min(dep['open_amount_usd'],cap)
                if amount>0:
                    aid=ds.ident('CPA');ds.add('corporate_billing/receipt_applications','application_id','One cash receipt or non-cash prepayment application to an invoice',application_id=aid,invoice_id=iid,receipt_id='',prepayment_id=dep['prepayment_id'],application_date=iso(end),property_id=p,amount_usd=amount,application_type='prepayment')
                    ds.post(end,'corporate_billing','receipt_applications',aid,[(p,'2220',amount),(p,'1100',-amount)],'corporate advance earned')
                    dep['open_amount_usd']-=amount;dep['applied_usd']+=amount;applied+=amount;cap-=amount
        due=end+timedelta(days=ct['payment_terms_days']);balance=total-applied;cashpaid=0
        delay=52 if co=='CO-001' and mo>='2026-08' else 8 if co=='CO-003' else 0
        for part,amt,paydate in [(1,mul(balance,.65),business(due+timedelta(days=delay))),(2,balance-mul(balance,.65),business(due+timedelta(days=delay+18)))]:
            if amt<=0 or paydate>CUT:continue
            rid=ds.ident('CRP');bid=ds.cash(paydate,p,amt,'corporate_receipt',rid,'1100','corporate_billing','receipts')
            ds.add('corporate_billing/receipts','receipt_id','One actual corporate bank receipt; partial allocation explicit',receipt_id=rid,company_id=co,property_id=p,receipt_date=iso(paydate),amount_usd=amt,bank_transaction_id=bid,remittance_reference=f'{iid}-P{part}')
            ds.add('corporate_billing/receipt_applications','application_id','One cash receipt or non-cash prepayment application to an invoice',application_id=ds.ident('CPA'),invoice_id=iid,receipt_id=rid,prepayment_id='',application_date=iso(paydate),property_id=p,amount_usd=amt,application_type='cash_receipt');cashpaid+=amt
        openamt=total-applied-cashpaid;overdue=max(0,(CUT-due).days)
        ds.add('corporate_billing/invoices','invoice_id','One corporate company/property/service-month earned invoice',invoice_id=iid,company_id=co,contract_id=ct['contract_id'],property_id=p,service_month=mo,invoice_date=iso(end),due_date=iso(due),net_usd=net,tax_usd=tax,total_usd=total,prepayment_applied_usd=applied,cash_applied_usd=cashpaid,open_ar_usd=openamt,days_past_due_at_cutoff=overdue if openamt else 0,aging_bucket='closed' if not openamt else 'current' if not overdue else '1_30' if overdue<=30 else '31_60' if overdue<=60 else '61_90' if overdue<=90 else 'over_90',expected_collection_date=iso(business(due+timedelta(days=delay+18))) if openamt else '',snapshot_date=iso(CUT))
    # Original group allotments are capacity requests, not sold nights.
    for p in PROPS:
        for d in months():
            start=d+timedelta(days=8);end=start+timedelta(days=3);bid=ds.ident('GBL')
            ds.add('corporate_billing/group_blocks','group_block_id','One contracted room allotment interval; no occupancy until reservation pickup',group_block_id=bid,company_id='CO-006',property_id=p,created_date=iso(d-timedelta(days=35)),arrival_date=iso(start),departure_date=iso(end),allotted_rooms=6 if p!='DUR' else 3,release_date=iso(start-timedelta(days=7)),contract_id=f'CT-CO-006-{p}',block_status='released',is_sold_room_night=False)
            for r in ds.res:
                if r['property_id']==p and r['company_id']=='CO-006' and start<=r['_a']<end and r['_kind']=='stay':
                    ds.add('corporate_billing/group_pickups','group_pickup_id','One picked-up reservation mapped to a group block',group_pickup_id=ds.ident('GPK'),group_block_id=bid,reservation_id=r['reservation_id'],picked_up_rooms=1)

def clean_private_fields(ds):
    for r in ds.res:
        for k in [k for k in r if k.startswith('_')]:del r[k]
